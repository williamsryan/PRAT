"""
Feature extraction module for PRAT.

Turns the feature-to-code mapping D_f (see :mod:`prat.mapping`) into the
``ExtractionResult`` consumed by reporting, the feature graph, and removal.

The mapping itself is the set difference D_f = L_all \\ L_f over *executed*
lines, per Algorithm 1. This module only partitions and presents it:

* files present in both builds contribute *interleaved* feature code — code
  that survives simply turning the build flag off, which is the paper's central
  observation;
* files present only in the feature-enabled build contribute *dedicated*
  feature code.

Both partitions are part of the same D_f and are summed into the reported total;
the split exists because the paper distinguishes them when contrasting PRAT
against manual build-flag deactivation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .gcov import load_coverage_dir
from .mapping import FeatureMapping, map_feature_from_coverage


@dataclass
class ExtractionResult:
    """Result of feature extraction operation."""

    success: bool
    file_line_counts: dict[str, int]  # source path -> removable line count
    total_removable_lines: int
    file_line_numbers: dict[str, list[int]]  # source path -> line numbers
    file_line_content: dict[str, list[str]]  # source path -> line content
    html_report_path: str | None = None
    dot_graph_path: str | None = None
    feature_graph_path: str | None = None
    error_message: str | None = None

    # Partition of D_f over files that exist only in the feature-enabled build.
    # These lines are already included in `total_removable_lines`; they are
    # tracked separately because the paper contrasts dedicated feature files
    # (which a build flag does exclude) against interleaved feature code in
    # shared files (which it does not).
    feature_only_file_counts: dict[str, int] = field(default_factory=dict)
    feature_only_removable_lines: int = 0
    feature_only_source_paths: list[str] = field(default_factory=list)

    # Lines executable with the feature enabled but executed in neither build.
    # Algorithm 1 deliberately leaves these in place; reporting the count makes
    # the soundness-over-completeness trade-off visible rather than silent.
    excluded_never_executed: int = 0

    # Contiguous (start, end) runs per file, the LOC-node unit of a feature
    # graph ("contiguous lines of code are merged in a single node").
    file_line_ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    @property
    def total_feature_lines(self) -> int:
        """|D_f|.

        Retained as an alias of ``total_removable_lines``: under the corrected
        set-difference mapping, interleaved and dedicated feature code are two
        partitions of the same D_f, so there is no second, larger "combined"
        figure to report.
        """
        return self.total_removable_lines

    @property
    def interleaved_removable_lines(self) -> int:
        """D_f restricted to files shared by both builds."""
        return self.total_removable_lines - self.feature_only_removable_lines


def _is_generated_idl(name: str) -> bool:
    """Return True for IDL-compiler-generated C++ files (TAO/OpenDDS).

    These regenerate wholesale when the IDL set changes, so they are mechanical
    churn rather than removable hand-written feature source. Patterns match TAO
    stubs/skeletons (`<Name>C.cpp`/`S.cpp`/`C.h`/`S.h`) and OpenDDS type support
    (`<Name>TypeSupportImpl/C/S.*`). These suffixes are C++-IDL specific and do
    not occur in the other targets (C/.rs sources), so this is a safe no-op for
    Mosquitto/FFmpeg/libaom/quiche.
    """
    base = os.path.basename(name)
    return (
        "TypeSupportImpl" in base
        or "TypeSupportC" in base
        or "TypeSupportS" in base
        or base.endswith(("C.cpp", "S.cpp", "C.h", "S.h", "C.inl", "S.inl"))
    )


def extract_from_mapping(
    mapping: FeatureMapping,
    skip_generated_idl: bool = False,
) -> ExtractionResult:
    """Build an ``ExtractionResult`` from a computed feature mapping D_f."""
    file_line_counts: dict[str, int] = {}
    file_line_numbers: dict[str, list[int]] = {}
    file_line_content: dict[str, list[str]] = {}
    file_line_ranges: dict[str, list[tuple[int, int]]] = {}
    feature_only_counts: dict[str, int] = {}
    feature_only_paths: list[str] = []
    feature_only_lines = 0
    total = 0

    for source_path, file_map in sorted(mapping.files.items()):
        if skip_generated_idl and _is_generated_idl(source_path):
            continue

        file_line_counts[source_path] = file_map.count
        file_line_numbers[source_path] = list(file_map.lines)
        file_line_content[source_path] = [
            file_map.source.get(line, "") for line in file_map.lines
        ]
        file_line_ranges[source_path] = file_map.ranges
        total += file_map.count

        if file_map.feature_only_file:
            feature_only_counts[source_path] = file_map.count
            feature_only_paths.append(source_path)
            feature_only_lines += file_map.count

    return ExtractionResult(
        success=True,
        file_line_counts=file_line_counts,
        total_removable_lines=total,
        file_line_numbers=file_line_numbers,
        file_line_content=file_line_content,
        file_line_ranges=file_line_ranges,
        feature_only_file_counts=feature_only_counts,
        feature_only_removable_lines=feature_only_lines,
        feature_only_source_paths=sorted(feature_only_paths),
        excluded_never_executed=mapping.excluded_never_executed,
    )


def extract_features(
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
    feature: str = "",
    skip_generated_idl: bool = False,
) -> ExtractionResult:
    """Compute D_f from two coverage directories and package it for reporting.

    Args:
        enabled_coverage_dir: Coverage of the build with all features enabled.
        disabled_coverage_dir: Coverage of the build with ``feature`` disabled.
        feature: Feature name, for labelling.
        skip_generated_idl: Drop IDL-generated C++ translation units.
    """
    print(f"[+] Mapping feature code: D_{feature or 'f'} = L_all \\ L_f")

    if not os.path.isdir(enabled_coverage_dir):
        return ExtractionResult(
            success=False,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=(
                f"Enabled coverage directory does not exist: {enabled_coverage_dir}"
            ),
        )

    if not os.path.isdir(disabled_coverage_dir):
        return ExtractionResult(
            success=False,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=(
                f"Disabled coverage directory does not exist: {disabled_coverage_dir}"
            ),
        )

    enabled = load_coverage_dir(enabled_coverage_dir)
    disabled = load_coverage_dir(disabled_coverage_dir)

    if not enabled:
        return ExtractionResult(
            success=False,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=f"No parseable coverage files in {enabled_coverage_dir}",
        )

    mapping = map_feature_from_coverage(feature, enabled, disabled)
    result = extract_from_mapping(mapping, skip_generated_idl=skip_generated_idl)

    print(f"[+] |D_f| = {result.total_removable_lines} lines "
          f"across {len(result.file_line_counts)} file(s)")
    if result.feature_only_removable_lines:
        print(f"    of which {result.feature_only_removable_lines} lines are in "
              f"{len(result.feature_only_file_counts)} dedicated feature file(s)")
    if result.excluded_never_executed:
        print(f"[+] {result.excluded_never_executed} executable line(s) never "
              f"executed in either build — retained (soundness over completeness)")

    return result
