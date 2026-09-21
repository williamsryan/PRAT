"""
Feature code removal module for PRAT.

Paper, Feature Removal: "It then performs feature removal by removing from the
source the lines in the union of D_i, and rebuilds the program binary. To ensure
that the program continues to work correctly after feature removal, the system
then re-runs the test suite, T ... and monitors the program's output for crashes
and unexpected behavior."

Two constraints shape this module.

*The build is a gate, not a log line.* The paper relies on compilation failure as
a safety net: "removing a feature without removing dependent features would
result in breaking the build, which would still prevent an incorrect
implementation from being generated." That only holds if a failed rebuild fails
the removal and restores the tree, which is what :func:`remove_feature_code`
does.

*Delimiter balance must be preserved.* D_f contains only lines gcov attributes
executable code to. A closing brace is not such a line, so ``if (x) {`` can
enter D_f while its matching ``}`` never can — blanking the opener alone closes
the enclosing function early. The balance guard therefore either absorbs the
adjacent non-executable structural lines needed to keep delimiters balanced, or
declines to remove that run. Absorbing a bare ``}`` is consistent with the
paper's granularity: it carries no coverage in either build, so it is neither
feature code nor shared code, it is the syntax of the block being removed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .extraction import ExtractionResult
from .gcov import merge_contiguous
from .mapping import FeatureMapping
from .mapping import protected_lines as mapping_protected


@dataclass
class RemovalResult:
    """Result of feature code removal."""

    success: bool
    lines_removed: int
    files_modified: int
    files_stubbed: int
    backup_dir: str | None = None
    rebuild_success: bool | None = None
    restored: bool = False
    error_message: str | None = None
    per_file_stats: dict[str, int] = field(default_factory=dict)

    # Runs the balance guard declined to remove, as
    # ``source_path -> [(start, end), ...]``. These lines stay in the source.
    skipped_unbalanced: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    # Non-executable structural lines absorbed to keep delimiters balanced.
    absorbed_structural: int = 0

    @property
    def skipped_line_count(self) -> int:
        return sum(
            end - start + 1
            for runs in self.skipped_unbalanced.values()
            for start, end in runs
        )


# ---------------------------------------------------------------------------
# Delimiter balance analysis
# ---------------------------------------------------------------------------

_OPENERS = "([{"
_CLOSERS = ")]}"


def compute_line_deltas(lines: list[str]) -> list[int]:
    """Return the net bracket delta contributed by each line.

    Skips delimiters inside string literals, character literals, line comments
    and block comments, carrying comment and continuation state across lines so
    a multi-line construct is accounted for correctly.

    Args:
        lines: File content as a list of lines (newlines optional).

    Returns:
        One integer per input line: opens minus closes.
    """
    deltas = [0] * len(lines)
    in_block_comment = False

    for index, raw in enumerate(lines):
        delta = 0
        position = 0
        length = len(raw)
        in_string: str | None = None

        while position < length:
            char = raw[position]

            if in_block_comment:
                if char == "*" and position + 1 < length and raw[position + 1] == "/":
                    in_block_comment = False
                    position += 2
                    continue
                position += 1
                continue

            if in_string is not None:
                if char == "\\":
                    position += 2
                    continue
                if char == in_string:
                    in_string = None
                position += 1
                continue

            if char == "/" and position + 1 < length:
                nxt = raw[position + 1]
                if nxt == "/":
                    break  # line comment: rest of the line is inert
                if nxt == "*":
                    in_block_comment = True
                    position += 2
                    continue

            if char in ("'", '"'):
                in_string = char
                position += 1
                continue

            if char in _OPENERS:
                delta += 1
            elif char in _CLOSERS:
                delta -= 1

            position += 1

        deltas[index] = delta

    return deltas


def _is_structural(text: str) -> bool:
    """True when a line contains only delimiters, whitespace and punctuation.

    These are the lines the guard may absorb: bare ``}``, ``);``, ``} else {``
    is deliberately excluded because ``else`` is a keyword.
    """
    stripped = text.strip()
    if not stripped:
        return True
    return all(char in "()[]{};, \t" for char in stripped)


def _bridge_structural_gaps(
    lines: list[str],
    runs: list[tuple[int, int]],
    protected: set[int],
) -> list[tuple[int, int]]:
    """Join runs separated only by non-executable structural lines.

    gcov attributes a function's entry block to its *signature* line while the
    opening brace on the next line gets ``-:``. So a removable function arrives
    as the runs ``[(sig, sig), (body_start, body_end)]`` with the ``{`` sitting in
    the gap. Checking those runs independently finds each balanced and approves
    both, leaving an orphaned ``{ ... }`` that does not compile.

    Bridging the gap makes the function one run, whose net delta is then +1 and
    whose closing brace the caller absorbs — so the whole function goes or none
    of it does. Only gaps made entirely of unprotected structural lines are
    bridged; those carry no coverage in either build, so they belong to whichever
    block encloses them.
    """
    if not runs:
        return runs

    bridged: list[tuple[int, int]] = [runs[0]]

    for start, end in runs[1:]:
        previous_start, previous_end = bridged[-1]
        gap = range(previous_end + 1, start)

        if gap and all(
            index not in protected and _is_structural(lines[index - 1])
            for index in gap
        ):
            bridged[-1] = (previous_start, end)
        else:
            bridged.append((start, end))

    return bridged


def plan_removal(
    lines: list[str],
    candidates: set[int],
    protected: set[int] | None = None,
) -> tuple[set[int], list[tuple[int, int]], int]:
    """Decide which candidate lines can be removed without unbalancing the file.

    Candidate lines are grouped into runs, runs separated only by non-executable
    structural lines are joined (see :func:`_bridge_structural_gaps`), and each
    run is then checked for delimiter balance. A run whose net delta is non-zero
    is repaired by absorbing the adjacent structural lines needed to close it;
    one that cannot be balanced that way is dropped rather than risking a
    corrupted file.

    Args:
        lines: File content.
        candidates: 1-indexed line numbers in D_f for this file.
        protected: 1-indexed lines that must never be removed (typically L_f,
            the lines still executed with the feature disabled).

    Returns:
        ``(approved, skipped_runs, absorbed)`` where ``approved`` is the set of
        1-indexed lines to remove, ``skipped_runs`` lists the ``(start, end)``
        runs declined, and ``absorbed`` counts extra lines pulled in.
    """
    protected = protected or set()
    deltas = compute_line_deltas(lines)
    total = len(lines)

    approved: set[int] = set()
    skipped: list[tuple[int, int]] = []
    absorbed = 0

    candidate_lines = {
        line for line in candidates if 1 <= line <= total and line not in protected
    }
    runs = _bridge_structural_gaps(
        lines, merge_contiguous(sorted(candidate_lines)), protected
    )

    for start, end in runs:
        run = set(range(start, end + 1))
        balance = sum(deltas[line - 1] for line in run)

        if balance > 0:
            # Unclosed openers: absorb following structural lines.
            cursor = end + 1
            while balance > 0 and cursor <= total:
                if cursor in protected or not _is_structural(lines[cursor - 1]):
                    break
                run.add(cursor)
                balance += deltas[cursor - 1]
                cursor += 1
        elif balance < 0:
            # Unmatched closers: absorb preceding structural lines.
            cursor = start - 1
            while balance < 0 and cursor >= 1:
                if cursor in protected or not _is_structural(lines[cursor - 1]):
                    break
                run.add(cursor)
                balance += deltas[cursor - 1]
                cursor -= 1

        if balance == 0:
            approved |= run
            # Lines pulled in that were not themselves candidates: bridged gaps
            # plus absorbed delimiters. Counted only for runs actually removed.
            absorbed += len(run - candidate_lines)
        else:
            # Cannot remove this run without corrupting the file. Leaving the
            # code in place is the conservative outcome the paper prefers.
            skipped.append((start, end))

    return approved, skipped, absorbed


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def remove_feature_code(
    extraction_result: ExtractionResult,
    project_path: str,
    feature: str,
    mapping: FeatureMapping | None = None,
    protected_lines: dict[str, set[int]] | None = None,
    stub_feature_only_files: bool = True,
    backup: bool = True,
    rebuild: bool = True,
    build_command: list[str] | None = None,
    balance_guard: bool = True,
    restore_on_build_failure: bool = True,
) -> RemovalResult:
    """Remove feature-specific code from the source tree and rebuild.

    Args:
        extraction_result: The mapping D_f, packaged for reporting.
        project_path: Path to project root.
        feature: Feature name, for logging and backup naming.
        mapping: Optional FeatureMapping; when given, lines still executed with
            the feature disabled are derived from it and protected.
        protected_lines: Explicit ``source_path -> lines`` that must survive.
            Merged with anything derived from ``mapping``.
        stub_feature_only_files: Replace files that exist only in the
            feature-enabled build with a stub, so build systems that list them
            unconditionally still resolve.
        backup: Create a backup of every file before modifying it.
        rebuild: Rebuild after removal and treat failure as removal failure.
        build_command: Rebuild command; auto-detected when None.
        balance_guard: Enforce delimiter balance. Disabling it reproduces the
            unguarded behaviour and can corrupt source files.
        restore_on_build_failure: Restore from backup when the rebuild fails.

    Returns:
        RemovalResult. ``success`` is False when the rebuild failed, so callers
        can treat a broken build as a failed removal.
    """
    project = Path(project_path)
    total_removed = 0
    files_modified = 0
    files_stubbed = 0
    per_file_stats: dict[str, int] = {}
    skipped_unbalanced: dict[str, list[tuple[int, int]]] = {}
    absorbed_total = 0
    backup_dir: str | None = None

    protected = {path: set(lines) for path, lines in (protected_lines or {}).items()}
    if mapping is not None:
        # Lines still executed with the feature disabled are shared code. D_f
        # already excludes them; protecting them explicitly also stops the
        # balance guard from absorbing them while repairing a run.
        for source_path, shared in mapping_protected(mapping).items():
            protected.setdefault(source_path, set()).update(shared)

    feature_only = set(extraction_result.feature_only_source_paths)

    print(f"\n[+] Removing {feature} feature code from {project_path}")
    print(f"    Target: {extraction_result.total_removable_lines} lines "
          f"across {len(extraction_result.file_line_counts)} file(s)")

    if backup:
        backup_dir = str(project / f"_backup_before_remove_{feature}")
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        os.makedirs(backup_dir)
        print(f"    Backup dir: {backup_dir}")

    try:
        for source_path, line_numbers in sorted(
            extraction_result.file_line_numbers.items()
        ):
            if not line_numbers:
                continue
            if stub_feature_only_files and source_path in feature_only:
                continue  # handled by the stubbing pass below

            source_file = _find_source_file(project, source_path)
            if source_file is None:
                print(f"    [!] Source file not found: {source_path}")
                continue

            _backup_file(source_file, project, backup_dir, backup)

            removed, skipped, absorbed = _remove_lines_from_file(
                source_file,
                set(line_numbers),
                protected=protected.get(source_path),
                balance_guard=balance_guard,
            )

            absorbed_total += absorbed
            if skipped:
                skipped_unbalanced[source_path] = skipped

            if removed > 0:
                files_modified += 1
                total_removed += removed
                per_file_stats[source_path] = removed
                note = f" ({absorbed} structural absorbed)" if absorbed else ""
                print(f"    {source_path}: removed {removed} lines{note}")

            if skipped:
                print(f"    {source_path}: declined {len(skipped)} unbalanced run(s)")

        if stub_feature_only_files:
            for source_path in sorted(feature_only):
                source_file = _find_source_file(project, source_path)
                if source_file is None:
                    continue

                _backup_file(source_file, project, backup_dir, backup)
                source_file.write_text(
                    f"/* {source_path}: feature code removed by PRAT "
                    f"(dedicated {feature} file) */\n",
                    encoding="utf-8",
                )
                files_stubbed += 1
                print(f"    {source_path}: stubbed (dedicated feature file)")

        print(f"\n    Summary: {total_removed} lines removed, "
              f"{files_modified} file(s) modified, {files_stubbed} file(s) stubbed")
        if skipped_unbalanced:
            count = sum(len(v) for v in skipped_unbalanced.values())
            print(f"    Balance guard declined {count} run(s) across "
                  f"{len(skipped_unbalanced)} file(s)")

        result = RemovalResult(
            success=True,
            lines_removed=total_removed,
            files_modified=files_modified,
            files_stubbed=files_stubbed,
            backup_dir=backup_dir,
            per_file_stats=per_file_stats,
            skipped_unbalanced=skipped_unbalanced,
            absorbed_structural=absorbed_total,
        )

        if not rebuild:
            return result

        print("\n[+] Rebuilding to verify removal...")
        result.rebuild_success = _rebuild_project(project_path, build_command)

        if result.rebuild_success:
            print("    [+] Rebuild successful — removal preserved compilation")
            return result

        # The paper treats a broken build as the safety net that prevents an
        # incorrect implementation being produced. Honour that: fail, and put
        # the tree back.
        print("    [!] Rebuild FAILED — removal broke compilation")
        result.success = False
        result.error_message = (
            "Rebuild failed after removal; the feature set is likely incomplete "
            "(a dependent feature may also need removing)"
        )

        if restore_on_build_failure and backup_dir:
            result.restored = restore_from_backup(backup_dir, project_path)
            if result.restored:
                print("    [+] Source tree restored from backup")
            else:
                print("    [!] Restore FAILED — tree left modified")

        return result

    except OSError as exc:
        return RemovalResult(
            success=False,
            lines_removed=total_removed,
            files_modified=files_modified,
            files_stubbed=files_stubbed,
            backup_dir=backup_dir,
            error_message=f"Feature removal failed: {exc}",
            per_file_stats=per_file_stats,
            skipped_unbalanced=skipped_unbalanced,
            absorbed_structural=absorbed_total,
        )


def restore_from_backup(backup_dir: str, project_path: str) -> bool:
    """Restore source files from a backup created during removal."""
    backup = Path(backup_dir)
    project = Path(project_path)

    if not backup.exists():
        print(f"[!] Backup directory not found: {backup_dir}")
        return False

    try:
        restored = 0
        for backup_file in backup.rglob("*"):
            if not backup_file.is_file():
                continue

            rel = backup_file.relative_to(backup)
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_file, target)
            restored += 1

        print(f"[+] Restored {restored} file(s) from backup")
        return True

    except OSError as exc:
        print(f"[!] Restoration failed: {exc}")
        return False


def _backup_file(
    source_file: Path,
    project: Path,
    backup_dir: str | None,
    backup: bool,
) -> None:
    if not (backup and backup_dir):
        return
    try:
        rel = source_file.relative_to(project)
    except ValueError:
        rel = Path(source_file.name)
    backup_path = Path(backup_dir) / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, backup_path)


def _find_source_file(project: Path, source_path: str) -> Path | None:
    """Locate a source file from the path gcov recorded.

    gcov's ``Source:`` header is relative to the build root, so the exact join
    normally resolves. The fallbacks handle out-of-tree builds and coverage
    output that carries only a basename.
    """
    exact = project / source_path
    if exact.is_file():
        return exact

    for search_dir in ("src", "lib", "build", "."):
        candidate = project / search_dir / source_path
        if candidate.is_file():
            return candidate

    basename = os.path.basename(source_path)
    for match in project.rglob(basename):
        if match.is_file() and "__pycache__" not in str(match):
            return match

    return None


def _remove_lines_from_file(
    file_path: Path,
    line_numbers: set[int],
    protected: set[int] | None = None,
    balance_guard: bool = True,
) -> tuple[int, list[tuple[int, int]], int]:
    """Blank the given lines in a source file.

    Lines are replaced with a bare newline rather than deleted so that line
    numbering is preserved, which keeps subsequent gcov output and any stored
    line mapping valid against the modified file.

    Returns:
        ``(removed, skipped_runs, absorbed)``.
    """
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except OSError as exc:
        print(f"    [!] Error reading {file_path}: {exc}")
        return 0, [], 0

    if balance_guard:
        approved, skipped, absorbed = plan_removal(lines, line_numbers, protected)
    else:
        total = len(lines)
        blocked = protected or set()
        approved = {
            line for line in line_numbers if 1 <= line <= total and line not in blocked
        }
        skipped, absorbed = [], 0

    if not approved:
        return 0, skipped, absorbed

    for line in approved:
        lines[line - 1] = "\n"

    try:
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
    except OSError as exc:
        print(f"    [!] Error writing {file_path}: {exc}")
        return 0, skipped, absorbed

    return len(approved), skipped, absorbed


def _rebuild_project(
    project_path: str,
    build_command: list[str] | None = None,
) -> bool:
    """Rebuild the project after code removal."""
    if build_command is None:
        project = Path(project_path)
        if (project / "Cargo.toml").exists():
            build_command = ["cargo", "build"]
        elif (project / "CMakeLists.txt").exists():
            build_command = ["make", "-C", "build", "-j"]
        elif (project / "Makefile").exists():
            build_command = ["make", "-j"]
        else:
            print("    [!] Cannot auto-detect build command")
            return False

    try:
        proc = subprocess.run(
            build_command,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
            for line in tail:
                print(f"      | {line}")
        return proc.returncode == 0

    except subprocess.TimeoutExpired:
        print("    [!] Rebuild timed out")
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"    [!] Rebuild error: {exc}")
        return False
