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

*Removal is conservative and fully accounted.* D_f contains only executable
lines observed by the coverage differential. The default path may also blank
adjacent non-executable delimiter-only lines needed to keep the source
syntactically balanced; these are reported separately as
``absorbed_structural`` and are not counted in |D_f|. It never expands to whole
files. If an edit remains unsafe or a mapped source cannot be located, removal
fails and restores the tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .extraction import ExtractionResult
from .gcov import merge_contiguous
from .mapping import FeatureMapping, GuardContext
from .mapping import guard_context as mapping_guard_context
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
    # ``source_path -> [(start, end), ...]``. These lines stay in the source and
    # count against exact removal.
    skipped_unbalanced: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    # Delimiter-only lines in D_f (a ``}`` gcov charged with a function's
    # epilogue) that shared code still needs. Kept; no code is retained.
    retained_structural: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    # Guard lines in D_f whose bodies the reduced build compiles but neither
    # build executed. Kept with their bodies, per the paper's rule against
    # removing unexecuted code.
    guards_shared_code: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    # Non-code lines absorbed to keep delimiters and conditionals balanced.
    absorbed_structural: int = 0
    # Unexecuted feature-only lines (no code in the reduced build) absorbed
    # because a run could not close without them. Disclosed, never in |D_f|.
    absorbed_unexecuted: int = 0
    missing_source_files: list[str] = field(default_factory=list)
    # Sources in D_f that lie outside the project tree (system headers whose
    # inline code the build executed). Never modified.
    out_of_tree_sources: list[str] = field(default_factory=list)
    target_lines: int = 0
    # Mapped lines kept by design (structural + guards of shared code), counted
    # exactly rather than from run spans, which can include bridged gap lines.
    retained_lines: int = 0

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


def _directive_kind(text: str) -> str | None:
    """Classify a preprocessor conditional line: ``if``, ``elif``, ``else``,
    ``endif``; None for anything else (including other directives)."""
    stripped = text.strip()
    if not stripped.startswith("#"):
        return None
    word = stripped[1:].lstrip().split(None, 1)[0] if stripped[1:].strip() else ""
    if word in ("if", "ifdef", "ifndef"):
        return "if"
    if word in ("elif", "else", "endif"):
        return word
    return None


@dataclass
class _ConditionalGroup:
    """One ``#if ... [#elif/#else ...] #endif`` group, by 1-indexed line."""

    opener: int
    branches: list[int] = field(default_factory=list)  # #elif / #else lines
    closer: int = 0

    @property
    def directives(self) -> set[int]:
        return {self.opener, self.closer, *self.branches}

    def arms(self) -> list[range]:
        """Line ranges of each arm, excluding the directive lines."""
        bounds = [self.opener, *self.branches, self.closer]
        return [range(a + 1, b) for a, b in zip(bounds, bounds[1:])]


def _conditional_groups(lines: list[str]) -> dict[int, _ConditionalGroup]:
    """Map every conditional directive line to its group.

    Unterminated or stray directives are left out; a run touching one of those
    fails the preprocessor check, which is the conservative outcome.
    """
    stack: list[_ConditionalGroup] = []
    by_line: dict[int, _ConditionalGroup] = {}
    for number, text in enumerate(lines, start=1):
        kind = _directive_kind(text)
        if kind == "if":
            stack.append(_ConditionalGroup(opener=number))
        elif kind in ("elif", "else") and stack:
            stack[-1].branches.append(number)
        elif kind == "endif" and stack:
            group = stack.pop()
            group.closer = number
            for line in group.directives:
                by_line[line] = group
    return by_line


@dataclass
class RemovalPlan:
    """Outcome of :func:`plan_removal` for one file.

    ``approved`` is every line to blank: candidates plus whatever the guard had
    to pull in. Declined candidate runs are split by why they stay:

    * ``skipped``: could not be balanced without touching code the reduced
      build keeps. These are genuine failures of exact removal.
    * ``retained_structural``: runs made only of delimiter text (a ``}`` gcov
      charged with a function epilogue) that shared code still needs. No code
      is kept by leaving them.
    * ``guards_shared_code``: a guard whose body is executable in the reduced
      build but was never executed in either build. Removing the guard would
      make that body unconditional; the paper's rule against removing
      unexecuted code means the guard must stay with it.
    """

    approved: set[int] = field(default_factory=set)
    skipped: list[tuple[int, int]] = field(default_factory=list)
    retained_structural: list[tuple[int, int]] = field(default_factory=list)
    guards_shared_code: list[tuple[int, int]] = field(default_factory=list)
    # Lines pulled in that carry no code in either build: delimiters, blanks,
    # comments, preprocessor lines, preprocessed-out alternatives.
    absorbed_structural: int = 0
    # Lines executable in the full build, never executed, and carrying no code
    # in the reduced build. Pulled in only when a run cannot otherwise close.
    absorbed_unexecuted: int = 0
    # Candidate lines inside each declined category.
    skipped_lines: int = 0
    retained_structural_lines: int = 0
    guards_shared_code_lines: int = 0

    @property
    def all_skipped(self) -> list[tuple[int, int]]:
        return sorted(self.skipped + self.retained_structural + self.guards_shared_code)

    @property
    def absorbed(self) -> int:
        return self.absorbed_structural + self.absorbed_unexecuted


class _Planner:
    """State for one :func:`plan_removal` call."""

    def __init__(
        self,
        lines: list[str],
        candidates: set[int],
        protected: set[int],
        absorbable: set[int],
        unexecuted_feature_only: set[int],
        unexecuted_shared: set[int],
        executable_disabled: set[int] | None = None,
    ) -> None:
        self.lines = lines
        self.total = len(lines)
        self.deltas = compute_line_deltas(lines)
        self.candidates = candidates
        self.protected = protected
        self.absorbable = absorbable
        self.unexecuted_feature_only = unexecuted_feature_only - protected - candidates
        self.unexecuted_shared = unexecuted_shared
        self.executable_disabled = executable_disabled or set()
        self.groups = _conditional_groups(lines)
        self.claimed: set[int] = set()

    # -- line classification -------------------------------------------------

    def is_noncode(self, line: int) -> bool:
        """A line the guard may blank because it carries no code in either
        build: delimiter-only text, or a line the coverage marks as such."""
        if line < 1 or line > self.total:
            return False
        if line in self.protected or line in self.candidates or line in self.claimed:
            return False
        return line in self.absorbable or _is_structural(self.lines[line - 1])

    def is_unexecuted_feature_only(self, line: int) -> bool:
        return line in self.unexecuted_feature_only and line not in self.claimed

    def is_directive(self, line: int) -> bool:
        return 1 <= line <= self.total and _directive_kind(self.lines[line - 1]) is not None

    def is_blank_or_comment(self, line: int) -> bool:
        if not (1 <= line <= self.total):
            return False
        text = self.lines[line - 1].strip()
        return not text or text.startswith("//") or (text.startswith("/*") and text.endswith("*/"))

    # -- runs ------------------------------------------------------------------

    def bridge_gaps(self, runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Join runs separated only by lines carrying no code.

        gcov attributes a function's entry block to its *signature* line while
        the opening brace on the next line gets ``-:``. Checking those runs
        independently finds each balanced and approves both, leaving an orphaned
        ``{ ... }`` that does not compile. Bridging makes the function one run,
        so the whole function goes or none of it does. Gaps are bridged only over
        lines that carry no code in either build; unexecuted feature code is not
        bridged over, it is absorbed only when a run cannot otherwise close.
        """
        if not runs:
            return runs
        bridged = [runs[0]]
        for start, end in runs[1:]:
            previous_start, previous_end = bridged[-1]
            gap = range(previous_end + 1, start)
            if gap and all(self.is_noncode(index) for index in gap):
                bridged[-1] = (previous_start, end)
            else:
                bridged.append((start, end))
        return bridged

    def balance(self, chosen: set[int]) -> int:
        return sum(self.deltas[line - 1] for line in chosen)

    # -- repairs -----------------------------------------------------------------

    def try_arm_swap(
        self, start: int, end: int, run: set[int]
    ) -> tuple[set[int], int] | None:
        """Remove the full-build arm of ``#if A / #else / #endif`` and keep the
        other arm as unconditional code.

        Mosquitto writes ``#ifdef WITH_TLS if(a || ssl){ #else if(a){ #endif``.
        The TLS header is in D_f, the plain header is live in the reduced build,
        and neither arm balances on its own. The rewrite is exact when the kept
        arm contributes the same delimiter delta as the removed one: the
        compiled text then keeps the structure the reduced build already had.
        """
        opener = start - 1
        while opener >= 1 and self.is_blank_or_comment(opener) and not self.is_directive(opener):
            opener -= 1
        if opener < 1 or _directive_kind(self.lines[opener - 1]) != "if":
            return None
        group = self.groups.get(opener)
        if group is None or len(group.branches) != 1:
            return None
        branch = group.branches[0]
        if _directive_kind(self.lines[branch - 1]) != "else":
            return None
        between = range(end + 1, branch)
        if not all(self.is_blank_or_comment(index) and not self.is_directive(index) for index in between):
            return None
        sibling = range(branch + 1, group.closer)
        if not sibling:
            return None
        for index in sibling:
            if index in self.candidates or index in self.claimed:
                return None
            if index not in self.protected and not self.is_noncode(index):
                return None
        if self.balance(set(sibling)) != self.balance(run):
            return None
        directives = {opener, branch, group.closer}
        if any(line in self.protected or line in self.candidates for line in directives):
            return None
        return run | directives, len(directives)

    def walk(
        self,
        run: set[int],
        balance: int,
        forward: bool,
        run_at: dict[int, int],
        runs: list[tuple[int, int]],
        consumed: set[int],
    ) -> tuple[set[int], list[int], list[int], set[int]] | str:
        """Extend ``run`` in one direction until its delimiters close.

        Lines met on the way are handled by kind: lines carrying no code are
        absorbed; unexecuted feature-only code is absorbed (it has no code in
        the reduced build, so removing it with its guard changes nothing the
        reduced build does); another candidate run is merged (forward only);
        protected lines are stepped over but their delta is tracked, and the
        walk succeeds only when that tracked delta is zero, so shared code is
        never re-nested — the one shape this admits is ``if(f){A}else{B}``
        collapsing to ``B``. Any other line is a wall: exact removal would need
        code the reduced build keeps.

        Returns the extended set with the absorbed lines by kind and the runs
        consumed, or a failure reason.
        """
        chosen = set(run)
        absorbed_noncode: list[int] = []
        absorbed_unexecuted: list[int] = []
        merged: set[int] = set()
        protected_delta = 0
        cursor = (max(run) + 1) if forward else (min(run) - 1)
        step = 1 if forward else -1

        while 1 <= cursor <= self.total:
            if balance == 0 and protected_delta == 0:
                return chosen, absorbed_noncode, absorbed_unexecuted, merged
            if cursor in self.claimed:
                return "unbalanced"
            if cursor in self.protected:
                protected_delta += self.deltas[cursor - 1]
                cursor += step
                continue
            if cursor in self.candidates:
                index = run_at.get(cursor)
                if not forward or index is None or index in consumed:
                    return "unbalanced"
                other_start, other_end = runs[index]
                other = set(range(other_start, other_end + 1))
                chosen |= other
                balance += self.balance(other)
                merged.add(index)
                cursor = other_end + 1
                continue
            if self.is_noncode(cursor):
                chosen.add(cursor)
                absorbed_noncode.append(cursor)
                balance += self.deltas[cursor - 1]
                cursor += step
                continue
            if self.is_unexecuted_feature_only(cursor):
                chosen.add(cursor)
                absorbed_unexecuted.append(cursor)
                balance += self.deltas[cursor - 1]
                cursor += step
                continue
            if cursor in self.unexecuted_shared:
                return "shared-unexecuted"
            return "unbalanced"

        if balance == 0 and protected_delta == 0:
            return chosen, absorbed_noncode, absorbed_unexecuted, merged
        return "unbalanced"

    def close_conditionals(self, chosen: set[int]) -> tuple[set[int], int] | None:
        """Make ``chosen`` consistent with the preprocessor structure.

        Every ``#if`` group with a directive in ``chosen`` must end up either
        fully removed (no non-directive line of the group survives) or with all
        surviving lines in a single arm, which then becomes unconditional. In
        both cases every directive of the group is blanked. Anything else means
        the removal would leave two arms compiled, and the run is declined.

        Returns the completed set and the number of directive lines added, or
        None when the structure cannot be closed.
        """
        added = 0
        pending = {line for line in chosen if line in self.groups}
        seen: set[int] = set()
        while pending:
            line = pending.pop()
            group = self.groups[line]
            if group.opener in seen:
                continue
            seen.add(group.opener)
            survivors_by_arm = [
                [index for index in arm if index not in chosen and index not in group.directives]
                for arm in group.arms()
            ]
            arms_with_survivors = [arm for arm in survivors_by_arm if arm]
            if len(arms_with_survivors) > 1:
                return None
            for directive in group.directives:
                if directive in self.protected or directive in self.candidates:
                    return None
                if directive in self.claimed:
                    return None
                if directive not in chosen:
                    chosen.add(directive)
                    added += 1
            # Directives inside surviving arms belong to nested groups that were
            # untouched; directives of removed arms are all in ``chosen`` now and
            # may themselves belong to nested groups, which must close too.
            for index in list(chosen):
                if index in self.groups and self.groups[index].opener not in seen:
                    pending.add(index)
        return chosen, added


def plan_removal(
    lines: list[str],
    candidates: set[int],
    protected: set[int] | None = None,
    absorb_structural: bool = True,
    absorbable: set[int] | None = None,
    unexecuted_feature_only: set[int] | None = None,
    unexecuted_shared: set[int] | None = None,
    executable_disabled: set[int] | None = None,
) -> tuple[set[int], list[tuple[int, int]], int]:
    """Decide which candidate lines can be removed without unbalancing the file.

    Thin wrapper over :func:`plan_removal_detailed` that keeps the historical
    ``(approved, skipped_runs, absorbed)`` shape. ``skipped_runs`` is every
    declined run regardless of category; ``absorbed`` counts every line pulled
    in that was not a candidate.
    """
    plan = plan_removal_detailed(
        lines,
        candidates,
        protected,
        absorb_structural,
        absorbable=absorbable,
        unexecuted_feature_only=unexecuted_feature_only,
        unexecuted_shared=unexecuted_shared,
        executable_disabled=executable_disabled,
    )
    return plan.approved, plan.all_skipped, plan.absorbed


def plan_removal_detailed(
    lines: list[str],
    candidates: set[int],
    protected: set[int] | None = None,
    absorb_structural: bool = True,
    absorbable: set[int] | None = None,
    unexecuted_feature_only: set[int] | None = None,
    unexecuted_shared: set[int] | None = None,
    executable_disabled: set[int] | None = None,
) -> RemovalPlan:
    """Decide which candidate lines can be removed without corrupting the file.

    Candidate lines are grouped into runs; runs separated only by lines carrying
    no code are joined; each run is then checked for delimiter balance. A run
    whose net delta is non-zero is repaired, in order of preference, by:

    1. the ``#if / #else / #endif`` arm swap (see ``_Planner.try_arm_swap``);
    2. walking outward, absorbing lines that carry no code in the reduced build
       and merging further candidate runs, stepping over shared code only when
       the stepped-over code is itself balanced (``if(f){A}else{B}`` to ``B``).

    Every approved set is then made consistent with the preprocessor structure:
    a conditional group touched by the removal is blanked entirely, and it may
    leave at most one arm's lines behind. A run that cannot be repaired is
    declined and classified (see :class:`RemovalPlan`).

    Args:
        lines: File content.
        candidates: 1-indexed line numbers in D_f for this file.
        protected: Lines that must never be removed (L_f, the lines still
            executed with the feature disabled).
        absorb_structural: Permit any absorption at all. When False, only runs
            that balance on their own are approved.
        absorbable: Lines carrying no code in either build (gcov ``-`` in the
            full build and not executable in the reduced build). Delimiter-only
            lines are always absorbable; this widens the set to comments,
            preprocessor lines and preprocessed-out alternatives.
        unexecuted_feature_only: Lines executable in the full build, never
            executed, and carrying no code in the reduced build. Absorbed only
            when a run cannot otherwise close.
        unexecuted_shared: Lines executable in both builds and executed in
            neither. Never removed; a run that would need one is declined as
            guarding shared code.
    """
    protected = protected or set()
    total = len(lines)
    candidate_lines = {
        line for line in candidates if 1 <= line <= total and line not in protected
    }
    planner = _Planner(
        lines,
        candidate_lines,
        protected,
        set(absorbable or ()),
        set(unexecuted_feature_only or ()),
        set(unexecuted_shared or ()),
        set(executable_disabled or ()),
    )
    plan = RemovalPlan()

    raw_runs = merge_contiguous(sorted(candidate_lines))
    runs = planner.bridge_gaps(raw_runs) if absorb_structural else raw_runs
    run_at = {
        line: index for index, (start, end) in enumerate(runs)
        for line in range(start, end + 1)
    }
    consumed: set[int] = set()

    def decline(index: int, reason: str) -> None:
        start, end = runs[index]
        run_candidates = candidate_lines & set(range(start, end + 1))
        if all(_is_structural(lines[line - 1]) for line in run_candidates):
            plan.retained_structural.append((start, end))
            plan.retained_structural_lines += len(run_candidates)
        elif reason == "shared-unexecuted" or any(
            line in planner.executable_disabled for line in run_candidates
        ):
            # Either closing the run needs code the reduced build compiles, or
            # the run itself is part of a function skeleton the reduced build
            # compiles (and never calls). Both stay, with that code.
            plan.guards_shared_code.append((start, end))
            plan.guards_shared_code_lines += len(run_candidates)
        else:
            plan.skipped.append((start, end))
            plan.skipped_lines += len(run_candidates)

    def approve(chosen: set[int], noncode: int, unexecuted: int, merged: set[int]) -> None:
        plan.approved |= chosen
        planner.claimed |= chosen
        plan.absorbed_structural += noncode
        plan.absorbed_unexecuted += unexecuted
        consumed.update(merged)

    for index, (start, end) in enumerate(runs):
        if index in consumed:
            continue
        run = set(range(start, end + 1))
        # Gap lines bridged into the run are absorbed non-code.
        bridged = len(run - candidate_lines)
        balance = planner.balance(run)
        merged: set[int] = set()

        if balance == 0:
            chosen, noncode, unexecuted = set(run), bridged, 0
        elif not absorb_structural:
            decline(index, "unbalanced")
            continue
        else:
            swapped = planner.try_arm_swap(start, end, run)
            if swapped is not None:
                chosen, noncode, unexecuted = swapped[0], bridged + swapped[1], 0
            else:
                walked = planner.walk(
                    run, balance, forward=balance > 0, run_at=run_at,
                    runs=runs, consumed=consumed,
                )
                if isinstance(walked, str):
                    decline(index, walked)
                    continue
                chosen, absorbed_noncode, absorbed_unexecuted, merged = walked
                noncode = bridged + len(absorbed_noncode)
                unexecuted = len(absorbed_unexecuted)

        if absorb_structural:
            closed = planner.close_conditionals(set(chosen))
            if closed is None:
                # Runs merged during the walk are NOT consumed: they are
                # processed on their own turn so every candidate line lands in
                # exactly one category.
                decline(index, "unbalanced")
                continue
            chosen, added = closed
            noncode += added
        elif any(planner.is_directive(line) for line in chosen if line not in candidate_lines):
            decline(index, "unbalanced")
            continue

        approve(chosen, noncode, unexecuted, merged)

    return plan


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def remove_feature_code(
    extraction_result: ExtractionResult,
    project_path: str,
    feature: str,
    mapping: FeatureMapping | None = None,
    protected_lines: dict[str, set[int]] | None = None,
    guard_context: dict[str, GuardContext] | None = None,
    stub_feature_only_files: bool = False,
    backup: bool = True,
    rebuild: bool = True,
    build_command: list[str] | None = None,
    build_commands: list[list[str]] | None = None,
    balance_guard: bool = True,
    allow_structural_absorption: bool = True,
    require_complete: bool = True,
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
        guard_context: Per-file line classes for the balance guard (see
            :func:`prat.mapping.guard_context`). Derived from ``mapping`` when
            not given. Without it the guard can only absorb delimiter-only
            lines, so exact removal fails more often.
        stub_feature_only_files: Legacy opt-in that replaces dedicated files.
            Disabled by default because whole-file stubbing removes lines that
            are outside D_f.
        backup: Create a backup of every file before modifying it.
        rebuild: Rebuild after removal and treat failure as removal failure.
        build_command: Rebuild command; auto-detected when None.
        build_commands: Ordered rebuild commands. Prefer this for adapters whose
            configuration and build are separate operations.
        balance_guard: Enforce delimiter balance. Disabling it reproduces the
            unguarded behaviour and can corrupt source files.
        allow_structural_absorption: Permit the balance guard to remove nearby
            non-executable delimiter lines, recorded separately from mapped
            lines. Enabled by default because gcov does not mark braces as
            executable even when their containing block is removed.
        require_complete: Fail and restore unless every mapped line is either
            removed or kept by design. Kept by design means a delimiter-only
            line shared code still needs, or a guard whose body the reduced
            build compiles but no test executed (removing it would strip
            unexecuted shared code, which the paper forbids). Both are listed
            in the result. Any other declined run fails the removal.
        restore_on_build_failure: Restore from backup when the rebuild fails.

    Returns:
        RemovalResult. ``success`` is False when the rebuild failed, so callers
        can treat a broken build as a failed removal.
    """
    # Resolve once: gcov often records absolute source paths (CMake builds do),
    # and the backup's relative layout, the restore, and the in-tree check all
    # depend on comparing against an absolute project root.
    project = Path(project_path).resolve()
    total_removed = 0
    files_modified = 0
    files_stubbed = 0
    per_file_stats: dict[str, int] = {}
    skipped_unbalanced: dict[str, list[tuple[int, int]]] = {}
    retained_structural: dict[str, list[tuple[int, int]]] = {}
    guards_shared_code: dict[str, list[tuple[int, int]]] = {}
    retained_lines = 0
    absorbed_total = 0
    absorbed_unexecuted_total = 0
    missing_source_files: list[str] = []
    out_of_tree_sources: list[str] = []
    backup_dir: str | None = None

    protected = {path: set(lines) for path, lines in (protected_lines or {}).items()}
    context: dict[str, GuardContext] = dict(guard_context or {})
    if mapping is not None:
        # Lines still executed with the feature disabled are shared code. D_f
        # already excludes them; protecting them explicitly also stops the
        # balance guard from absorbing them while repairing a run.
        for source_path, shared in mapping_protected(mapping).items():
            protected.setdefault(source_path, set()).update(shared)
        for source_path, file_context in mapping_guard_context(mapping).items():
            context.setdefault(source_path, file_context)

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
                if _is_outside(project, source_path):
                    # A system header (an inline function in OpenSSL's headers,
                    # say) can appear in D_f because the build executed it,
                    # but it is not part of P and PRAT must never write to it.
                    print(f"    [!] Not in the project tree, left untouched: "
                          f"{source_path}")
                    out_of_tree_sources.append(source_path)
                    continue
                print(f"    [!] Source file not found: {source_path}")
                missing_source_files.append(source_path)
                continue

            _backup_file(source_file, project, backup_dir, backup)

            plan = _remove_lines_from_file(
                source_file,
                set(line_numbers),
                protected=protected.get(source_path),
                balance_guard=balance_guard,
                allow_structural_absorption=allow_structural_absorption,
                context=context.get(source_path),
            )
            removed = len(plan.approved & set(line_numbers))

            absorbed_total += plan.absorbed_structural
            absorbed_unexecuted_total += plan.absorbed_unexecuted
            if plan.skipped:
                skipped_unbalanced[source_path] = plan.skipped
            if plan.retained_structural:
                retained_structural[source_path] = plan.retained_structural
            if plan.guards_shared_code:
                guards_shared_code[source_path] = plan.guards_shared_code
            retained_lines += plan.retained_structural_lines + plan.guards_shared_code_lines

            if removed > 0:
                files_modified += 1
                total_removed += removed
                per_file_stats[source_path] = removed
                notes = []
                if plan.absorbed_structural:
                    notes.append(f"{plan.absorbed_structural} structural absorbed")
                if plan.absorbed_unexecuted:
                    notes.append(f"{plan.absorbed_unexecuted} unexecuted feature-only absorbed")
                note = f" ({', '.join(notes)})" if notes else ""
                print(f"    {source_path}: removed {removed} lines{note}")

            if plan.retained_structural:
                print(f"    {source_path}: kept {plan.retained_structural_lines} "
                      f"delimiter line(s) shared code still needs")
            if plan.guards_shared_code:
                print(f"    {source_path}: kept {plan.guards_shared_code_lines} "
                      f"guard line(s) whose unexecuted bodies the reduced build compiles")
            if plan.skipped:
                print(f"    {source_path}: declined {len(plan.skipped)} unbalanced run(s)")

        if stub_feature_only_files:
            for source_path in sorted(feature_only):
                source_file = _find_source_file(project, source_path)
                if source_file is None:
                    missing_source_files.append(source_path)
                    continue

                _backup_file(source_file, project, backup_dir, backup)
                source_file.write_text(
                    f"/* {source_path}: feature code removed by PRAT "
                    f"(dedicated {feature} file) */\n",
                    encoding="utf-8",
                )
                files_stubbed += 1
                print(f"    {source_path}: stubbed (dedicated feature file)")

        # Exact removal: every mapped line is removed, or kept for one of the
        # two disclosed reasons. Kept lines are counted from the plans, not
        # from run spans, so bridged gap lines never inflate the figure.
        accounted = total_removed + retained_lines
        incomplete = (
            accounted != extraction_result.total_removable_lines
            or bool(skipped_unbalanced)
            or bool(missing_source_files)
        )
        if require_complete and incomplete:
            message = (
                f"Exact removal incomplete: removed {total_removed} of "
                f"{extraction_result.total_removable_lines} mapped line(s)"
            )
            if retained_lines:
                message += f" ({retained_lines} kept by design)"
            if missing_source_files:
                message += f"; {len(missing_source_files)} source file(s) missing"
            if out_of_tree_sources:
                message += (
                    f"; {len(out_of_tree_sources)} source(s) outside the project "
                    "tree were left untouched"
                )
            if skipped_unbalanced:
                message += "; one or more mapped ranges were syntactically unsafe"
            restored = bool(backup_dir and restore_from_backup(backup_dir, project_path))
            return RemovalResult(
                success=False,
                lines_removed=total_removed,
                files_modified=files_modified,
                files_stubbed=files_stubbed,
                backup_dir=backup_dir,
                restored=restored,
                error_message=message,
                per_file_stats=per_file_stats,
                skipped_unbalanced=skipped_unbalanced,
                retained_structural=retained_structural,
                guards_shared_code=guards_shared_code,
                absorbed_structural=absorbed_total,
                absorbed_unexecuted=absorbed_unexecuted_total,
                missing_source_files=missing_source_files,
                out_of_tree_sources=out_of_tree_sources,
                target_lines=extraction_result.total_removable_lines,
                retained_lines=retained_lines,
            )

        print(f"\n    Summary: {total_removed} lines removed, "
              f"{files_modified} file(s) modified, {files_stubbed} file(s) stubbed")
        if absorbed_unexecuted_total:
            print(f"    Absorbed {absorbed_unexecuted_total} unexecuted feature-only "
                  f"line(s) (no code in the reduced build) to close runs")
        if retained_lines:
            print(f"    Kept {retained_lines} mapped line(s) by design: "
                  f"{sum(len(v) for v in retained_structural.values())} delimiter run(s), "
                  f"{sum(len(v) for v in guards_shared_code.values())} guard(s) of "
                  f"unexecuted shared code")
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
            retained_structural=retained_structural,
            guards_shared_code=guards_shared_code,
            absorbed_structural=absorbed_total,
            absorbed_unexecuted=absorbed_unexecuted_total,
            missing_source_files=missing_source_files,
            out_of_tree_sources=out_of_tree_sources,
            target_lines=extraction_result.total_removable_lines,
            retained_lines=retained_lines,
        )

        if not rebuild:
            return result

        print("\n[+] Rebuilding to verify removal...")
        result.rebuild_success = _rebuild_project(
            project_path, build_command, build_commands
        )

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
        restored = False
        if backup_dir:
            restored = restore_from_backup(backup_dir, project_path)
        return RemovalResult(
            success=False,
            lines_removed=total_removed,
            files_modified=files_modified,
            files_stubbed=files_stubbed,
            backup_dir=backup_dir,
            error_message=f"Feature removal failed: {exc}",
            per_file_stats=per_file_stats,
            skipped_unbalanced=skipped_unbalanced,
            retained_structural=retained_structural,
            guards_shared_code=guards_shared_code,
            absorbed_structural=absorbed_total,
            absorbed_unexecuted=absorbed_unexecuted_total,
            missing_source_files=missing_source_files,
            out_of_tree_sources=out_of_tree_sources,
            target_lines=extraction_result.total_removable_lines,
            restored=restored,
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
    # The backup mirrors the project layout, so restore_from_backup can put
    # every file back where it came from. _find_source_file only returns
    # in-tree files, so relative_to cannot fail here.
    rel = source_file.resolve().relative_to(project.resolve())
    backup_path = Path(backup_dir) / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, backup_path)


def _is_outside(project: Path, source_path: str) -> bool:
    """Whether a gcov-recorded source path points outside the project tree."""
    candidate = Path(source_path)
    if not candidate.is_absolute():
        return False
    try:
        candidate.resolve().relative_to(project.resolve())
    except ValueError:
        return True
    return False


def _find_source_file(project: Path, source_path: str) -> Path | None:
    """Locate a source file from the path gcov recorded.

    gcov's ``Source:`` header is relative to the build root, so the exact join
    normally resolves. The fallbacks handle out-of-tree builds and coverage
    output that carries only a basename. A path that resolves outside the
    project tree (an absolute path into a system include directory) is never
    returned: PRAT modifies the program under analysis, not its toolchain.
    """
    project = project.resolve()

    def in_tree(path: Path) -> Path | None:
        resolved = path.resolve()
        try:
            resolved.relative_to(project)
        except ValueError:
            return None
        return resolved if resolved.is_file() else None

    exact = in_tree(project / source_path)
    if exact is not None:
        return exact

    if _is_outside(project, source_path):
        return None

    for search_dir in ("src", "lib", "build", "."):
        candidate = in_tree(project / search_dir / source_path)
        if candidate is not None:
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
    allow_structural_absorption: bool = False,
    context: GuardContext | None = None,
) -> RemovalPlan:
    """Blank the given lines in a source file.

    Lines are replaced with a bare newline rather than deleted so that line
    numbering is preserved, which keeps subsequent gcov output and any stored
    line mapping valid against the modified file.

    Returns:
        The :class:`RemovalPlan` that was applied. ``approved`` is empty when
        the file could not be read or written.
    """
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except OSError as exc:
        print(f"    [!] Error reading {file_path}: {exc}")
        return RemovalPlan()

    if balance_guard:
        plan = plan_removal_detailed(
            lines,
            line_numbers,
            protected,
            absorb_structural=allow_structural_absorption,
            absorbable=set(context.absorbable) if context else None,
            unexecuted_feature_only=(
                set(context.unexecuted_feature_only) if context else None
            ),
            unexecuted_shared=set(context.unexecuted_shared) if context else None,
            executable_disabled=set(context.executable_disabled) if context else None,
        )
    else:
        total = len(lines)
        blocked = protected or set()
        plan = RemovalPlan(approved={
            line for line in line_numbers if 1 <= line <= total and line not in blocked
        })

    if not plan.approved:
        return plan

    for line in plan.approved:
        lines[line - 1] = "\n"

    try:
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
    except OSError as exc:
        print(f"    [!] Error writing {file_path}: {exc}")
        plan.approved = set()
        return plan

    return plan


def _rebuild_project(
    project_path: str,
    build_command: list[str] | None = None,
    build_commands: list[list[str]] | None = None,
) -> bool:
    """Rebuild the project after code removal."""
    commands: list[list[str]]
    if build_commands is not None:
        commands = build_commands
    elif build_command is not None:
        commands = [build_command]
    else:
        project = Path(project_path)
        if (project / "Cargo.toml").exists():
            commands = [["cargo", "build"]]
        elif (project / "CMakeLists.txt").exists():
            commands = [["cmake", "--build", "build", "--parallel"]]
        elif (project / "Makefile").exists():
            commands = [["make", "-j"]]
        else:
            print("    [!] Cannot auto-detect build command")
            return False

    try:
        for command in commands:
            proc = subprocess.run(
                command,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
                for line in tail:
                    print(f"      | {line}")
                return False
        return True

    except subprocess.TimeoutExpired:
        print("    [!] Rebuild timed out")
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"    [!] Rebuild error: {exc}")
        return False
