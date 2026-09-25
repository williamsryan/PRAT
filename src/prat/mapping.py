"""
Feature-to-code mapping for PRAT — Algorithm 1, lines 9-11.

This module computes the paper's mapping directly as a set difference over
executed lines:

    D_f = L_all \\ L_f

where L_all is the set of lines executed by the test suite T against the build
with all features enabled, and L_f is the set executed against the build with
feature f disabled.

Three properties the paper states explicitly, and which this module makes true
by construction rather than by approximation:

1. Only lines *executed* with the feature active are candidates. A line that
   never executes in either build is never in D_f ("The algorithm does not
   remove LOCs that are never executed regardless of whether the feature is
   active or not").
2. Lines executed in the feature-disabled build are excluded, so code shared
   with other functionality survives.
3. Soundness over completeness: incomplete test coverage shrinks D_f, it never
   pulls in unrelated lines.

A source file present only in the feature-enabled build is handled by the same
rule with L_f = {} for that file, so D_f is its executed line set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .gcov import GcovFile, format_ranges, load_coverage_dir, merge_contiguous


@dataclass
class FileMapping:
    """Lines of one source file attributed exclusively to a feature.

    Attributes:
        source_path: Source path as recorded by gcov, relative to the build
            root (e.g. ``src/net.c``).
        lines: Sorted line numbers in D_f for this file.
        source: Line number -> source text, for the lines in ``lines``.
        feature_only_file: True when the file exists only in the
            feature-enabled build, so every executed line is feature code.
        executed_enabled: |L_all| restricted to this file, for reporting.
        executed_disabled: |L_f| restricted to this file, for reporting.
        shared_lines: L_f restricted to this file — lines still executed with
            the feature disabled. Removal must never touch these, so the set is
            carried through rather than just its size.
        never_executed_both: Lines executable in the enabled build but never
            executed in either. Reported, never removed as D_f — this is the
            category the paper's conservatism excludes.
        absorbable_lines: Lines carrying no code in either build: gcov ``-`` in
            the enabled build (blank, comment, delimiter, preprocessor line,
            preprocessed-out alternative) and not executable in the disabled
            build. The removal guard may blank these to keep a file balanced.
        unexecuted_feature_only: ``never_executed_both`` restricted to lines
            with no code in the disabled build. Feature code the tests never
            reached; removing it alongside its guard changes nothing the reduced
            build does. The guard absorbs such a line only when a run cannot
            otherwise close, and reports it separately.
        unexecuted_shared: Code the disabled build compiles that no build
            executed: shared lines the tests never reached, and disabled-only
            stubs such as the ``#else`` arm of a feature conditional. Never
            removed, and a guard whose body needs one stays too.
        executable_disabled: Every line the disabled build compiles. A D_f line
            in this set is a skeleton the reduced build keeps (the signature
            or closing brace of a function B_f compiles but never calls);
            removing it would orphan the reduced build's own body.
    """

    source_path: str
    lines: list[int] = field(default_factory=list)
    source: dict[int, str] = field(default_factory=dict)
    feature_only_file: bool = False
    executed_enabled: int = 0
    executed_disabled: int = 0
    shared_lines: set[int] = field(default_factory=set)
    never_executed_both: list[int] = field(default_factory=list)
    absorbable_lines: set[int] = field(default_factory=set)
    unexecuted_feature_only: set[int] = field(default_factory=set)
    unexecuted_shared: set[int] = field(default_factory=set)
    executable_disabled: set[int] = field(default_factory=set)

    @property
    def count(self) -> int:
        return len(self.lines)

    @property
    def ranges(self) -> list[tuple[int, int]]:
        """Contiguous ``(start, end)`` runs, the feature-graph LOC node unit."""
        return merge_contiguous(self.lines)

    @property
    def range_label(self) -> str:
        return format_ranges(self.lines)


@dataclass
class FeatureMapping:
    """D_f for one feature, across all source files.

    Attributes:
        feature: Feature name f.
        files: source_path -> FileMapping, only for files with a non-empty D_f.
        excluded_never_executed: Total lines excluded because they are never
            executed in either build. Surfacing this makes the soundness
            trade-off visible instead of silent.
    """

    feature: str
    files: dict[str, FileMapping] = field(default_factory=dict)
    excluded_never_executed: int = 0

    @property
    def total_lines(self) -> int:
        """|D_f|."""
        return sum(m.count for m in self.files.values())

    @property
    def file_line_counts(self) -> dict[str, int]:
        return {path: m.count for path, m in self.files.items()}

    @property
    def file_line_numbers(self) -> dict[str, list[int]]:
        return {path: list(m.lines) for path, m in self.files.items()}

    @property
    def file_line_content(self) -> dict[str, list[str]]:
        return {
            path: [m.source.get(line, "") for line in m.lines]
            for path, m in self.files.items()
        }

    @property
    def feature_only_files(self) -> list[str]:
        return sorted(p for p, m in self.files.items() if m.feature_only_file)


def map_feature_from_coverage(
    feature: str,
    enabled: dict[str, GcovFile],
    disabled: dict[str, GcovFile],
) -> FeatureMapping:
    """Compute D_f = L_all \\ L_f from two parsed coverage sets.

    Args:
        feature: Feature name, for labelling.
        enabled: Parsed coverage of B_all (all features on), keyed by source path.
        disabled: Parsed coverage of B_f (feature f off), keyed by source path.

    Returns:
        FeatureMapping holding D_f per source file.
    """
    mapping = FeatureMapping(feature=feature)

    for source_path, cov_enabled in enabled.items():
        cov_disabled = disabled.get(source_path)

        # L_f restricted to this file. A file absent from the disabled build
        # contributes nothing to L_f, which is the correct reading of
        # Algorithm 1 rather than a special case.
        lines_disabled = cov_disabled.executed if cov_disabled else set()

        d_lines = sorted(cov_enabled.executed - lines_disabled)

        # Executable in the enabled build but executed in neither. Excluded by
        # the paper's conservatism; counted so the user can see how much
        # potential removal the test suite is leaving on the table.
        never_both = sorted(
            cov_enabled.never_executed
            - lines_disabled
            - (cov_disabled.executed if cov_disabled else set())
        )
        mapping.excluded_never_executed += len(never_both)

        if not d_lines:
            continue

        # What the reduced build compiles at each line decides what the removal
        # guard may touch. A file absent from B_f compiles nothing there.
        executable_disabled = cov_disabled.executable if cov_disabled else set()
        never_both_set = set(never_both)
        # Code B_f compiles that no build executed: unexecuted lines shared by
        # both builds, plus B_f-only stubs (the ``#else`` arm of a feature
        # conditional). D_f lines are excluded by construction.
        unexecuted_shared = (
            (cov_disabled.never_executed - cov_enabled.executed) if cov_disabled else set()
        )

        mapping.files[source_path] = FileMapping(
            source_path=source_path,
            lines=d_lines,
            source={line: cov_enabled.source.get(line, "") for line in d_lines},
            feature_only_file=cov_disabled is None,
            executed_enabled=len(cov_enabled.executed),
            executed_disabled=len(lines_disabled),
            shared_lines=set(lines_disabled),
            never_executed_both=never_both,
            absorbable_lines=cov_enabled.non_executable - executable_disabled,
            unexecuted_feature_only=never_both_set - executable_disabled,
            unexecuted_shared=unexecuted_shared,
            executable_disabled=set(executable_disabled),
        )

    return mapping


def protected_lines(mapping: FeatureMapping) -> dict[str, set[int]]:
    """Lines that must survive removal, as ``source_path -> lines``.

    These are the lines still executed with the feature disabled (L_f). D_f
    already excludes them, so this is a defence-in-depth input for
    :func:`prat.removal.remove_feature_code` — it stops the balance guard from
    absorbing shared code while repairing a run.
    """
    return {
        path: set(file_map.shared_lines)
        for path, file_map in mapping.files.items()
        if file_map.shared_lines
    }


@dataclass(frozen=True)
class GuardContext:
    """Per-file line classes the removal guard consults beyond D_f and L_f.

    See :class:`FileMapping` for the meaning of each set.
    """

    absorbable: frozenset[int] = frozenset()
    unexecuted_feature_only: frozenset[int] = frozenset()
    unexecuted_shared: frozenset[int] = frozenset()
    executable_disabled: frozenset[int] = frozenset()


def guard_context(mapping: FeatureMapping) -> dict[str, GuardContext]:
    """Guard context for every file in D_f, as ``source_path -> GuardContext``."""
    return {
        path: GuardContext(
            absorbable=frozenset(file_map.absorbable_lines),
            unexecuted_feature_only=frozenset(file_map.unexecuted_feature_only),
            unexecuted_shared=frozenset(file_map.unexecuted_shared),
            executable_disabled=frozenset(file_map.executable_disabled),
        )
        for path, file_map in mapping.files.items()
    }


def map_feature(
    feature: str,
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
) -> FeatureMapping:
    """Compute D_f from two directories of ``.gcov`` files.

    Args:
        feature: Feature name f.
        enabled_coverage_dir: Coverage directory for the all-features build.
        disabled_coverage_dir: Coverage directory for the feature-disabled build.
    """
    return map_feature_from_coverage(
        feature,
        load_coverage_dir(enabled_coverage_dir),
        load_coverage_dir(disabled_coverage_dir),
    )


def coverage_totals(coverage: dict[str, GcovFile]) -> tuple[int, int]:
    """Return ``(covered_lines, executable_lines)`` across a coverage set.

    Used to report the line-coverage figures the paper's evaluation quotes for
    its test suites.
    """
    covered = sum(len(c.executed) for c in coverage.values())
    executable = sum(len(c.executable) for c in coverage.values())
    return covered, executable


def coverage_percent(coverage: dict[str, GcovFile]) -> float | None:
    """Line coverage as a percentage, or None when nothing is instrumented."""
    covered, executable = coverage_totals(coverage)
    if executable == 0:
        return None
    return 100.0 * covered / executable


def restrict_to_project(
    coverage: dict[str, GcovFile], project_path: str
) -> tuple[dict[str, GcovFile], list[str]]:
    """Drop coverage for sources outside the project tree.

    gcov reports every compilation unit the build executed, which includes
    inline functions from system headers (OpenSSL's ``x509v3.h`` under a TLS
    build, for instance). Those lines are not part of the program P that
    Algorithm 1 maps and removal must never touch them, so they are removed
    from L_all and L_f before ``D_f`` is computed. Relative source paths are
    kept: gcov records them relative to the build root, inside the tree.

    Returns the filtered coverage and the source paths that were dropped.
    """
    root = Path(project_path).resolve()
    kept: dict[str, GcovFile] = {}
    dropped: list[str] = []
    for source_path, gcov_file in coverage.items():
        candidate = Path(source_path)
        if candidate.is_absolute():
            try:
                candidate.resolve().relative_to(root)
            except ValueError:
                dropped.append(source_path)
                continue
        kept[source_path] = gcov_file
    return kept, sorted(dropped)


def function_totals(coverage: dict[str, GcovFile]) -> tuple[int, int]:
    """Return ``(covered_functions, total_functions)`` across a coverage set.

    Only non-zero when gcov was run with ``-f``. The paper's fuzzing table
    reports function coverage alongside line coverage, so both are available.
    """
    covered = 0
    total = 0
    for gcov in coverage.values():
        file_covered, file_total = gcov.function_coverage()
        covered += file_covered
        total += file_total
    return covered, total


def function_percent(coverage: dict[str, GcovFile]) -> float | None:
    """Function coverage as a percentage, or None when no functions were seen."""
    covered, total = function_totals(coverage)
    if total == 0:
        return None
    return 100.0 * covered / total
