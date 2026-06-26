"""
Feature extraction module for PRAT.

This module handles parsing diff files to identify and count feature-specific
lines of code that can be removed.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExtractionResult:
    """Result of feature extraction operation."""
    success: bool
    file_line_counts: dict[str, int]  # filename -> removable line count
    total_removable_lines: int
    file_line_numbers: dict[str, list[int]]  # filename -> list of line numbers
    file_line_content: dict[str, list[str]]  # filename -> list of line content
    html_report_path: Optional[str] = None
    dot_graph_path: Optional[str] = None
    error_message: Optional[str] = None
    # --- Paper-aligned (dedicated feature file) metric -----------------------
    # PRAT's primary `total_removable_lines` counts feature code INTERLEAVED in
    # files shared by both builds. The paper's "lines removed", however, also
    # includes whole source files that exist only when the feature is enabled
    # (e.g. libx264.c, wsio.c, the OpenDDS security/ tree). These are tracked
    # separately here so both measures are visible without silently changing
    # the primary metric (which keeps the interleaved-feature demos comparable).
    feature_only_file_counts: dict[str, int] = field(default_factory=dict)
    feature_only_removable_lines: int = 0
    total_feature_lines: int = 0  # interleaved + feature-only (paper-aligned)
    # Real relative source paths of feature-only files, parsed from each gcov
    # "Source:" header (e.g. "av1/encoder/rdopt.c"). Enables directory-style
    # key_file verification that flat basenames cannot support.
    feature_only_source_paths: list[str] = field(default_factory=list)


def _gcov_source_path(gcov_file: str) -> Optional[str]:
    """Parse the relative source path from a gcov file's "Source:" header.

    gcov files begin with header lines like:
        ``        -:    0:Source:av1/encoder/rdopt.c``
    Returns the path (e.g. "av1/encoder/rdopt.c") or None if not found.
    """
    try:
        with open(gcov_file, encoding="utf-8", errors="ignore") as f:
            for _ in range(8):  # header is at the very top
                line = f.readline()
                if not line:
                    break
                marker = ":Source:"
                idx = line.find(marker)
                if idx != -1:
                    return line[idx + len(marker):].strip()
    except Exception:
        return None
    return None


def _is_generated_idl(name: str) -> bool:
    """Return True for IDL-compiler-generated C++ files (TAO/OpenDDS).

    These regenerate wholesale when the IDL set changes, so they are mechanical
    churn rather than removable hand-written feature source. Patterns match TAO
    stubs/skeletons (`<Name>C.cpp`/`S.cpp`/`C.h`/`S.h`) and OpenDDS type support
    (`<Name>TypeSupportImpl/C/S.*`). These suffixes are C++-IDL specific and do
    not occur in the other targets (C/.rs sources), so this is a safe no-op for
    Mosquitto/FFmpeg/libaom/quiche.
    """
    return (
        "TypeSupportImpl" in name
        or "TypeSupportC" in name
        or "TypeSupportS" in name
        or name.endswith(("C.cpp", "S.cpp", "C.h", "S.h", "C.inl", "S.inl"))
    )


def count_removable_lines(diff_file: str) -> int:
    """
    Count lines marked with ##### in a diff file.

    Args:
        diff_file: Path to diff file

    Returns:
        Count of never-executed lines (marked with #####)
    """
    if not os.path.exists(diff_file):
        return 0

    count = 0
    try:
        with open(diff_file, encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Look for ##### markers (never-executed code)
                # Exclude /*EOF*/ markers
                if '#####' in line and '/*EOF*/' not in line:
                    count += 1
    except Exception as e:
        print(f"[-] Error reading {diff_file}: {e}")
        return 0

    return count


def extract_features(
    diff_dir: str,
    feature: str = "",
    output_dir: Optional[str] = None,
    enabled_coverage_dir: Optional[str] = None,
    feature_only_files: Optional[list[str]] = None) -> ExtractionResult:
    """
    Parse diff files and extract feature-specific code.

    Args:
        diff_dir: Directory containing diff files
        feature: Feature name (used for report labeling)
        output_dir: Base directory for output reports (default: current directory)
        enabled_coverage_dir: Coverage dir for the feature-ENABLED build. When
            provided together with feature_only_files, the never-executed lines
            of dedicated feature files are counted as the paper-aligned metric.
        feature_only_files: Base names (without .gcov) of coverage files that
            exist only in the enabled build (from DiffResult.feature_only_files).

    Returns:
        ExtractionResult with line counts and file mappings
    """
    print(f"[+] Extract features for removal from: {diff_dir}")

    def _count_feature_only() -> tuple[dict[str, int], int, list[str]]:
        """Count never-executed (#####) lines in dedicated feature files.

        Also returns the real relative source paths parsed from each gcov
        "Source:" header (e.g. "av1/encoder/rdopt.c"), which lets downstream
        consumers verify directory-style key files that flat basenames cannot.
        """
        counts: dict[str, int] = {}
        total = 0
        paths: list[str] = []
        if not (enabled_coverage_dir and feature_only_files):
            return counts, total, paths
        for name in feature_only_files:
            if _is_generated_idl(name):
                continue
            gcov_path = os.path.join(enabled_coverage_dir, f"{name}.gcov")
            if not os.path.exists(gcov_path):
                # Coverage files are stored without a trailing .gcov when the
                # source already carries an extension differing from .gcov.
                alt = os.path.join(enabled_coverage_dir, name)
                gcov_path = alt if os.path.exists(alt) else gcov_path
            if os.path.exists(gcov_path):
                c = count_removable_lines(gcov_path)
                if c > 0:
                    counts[name] = c
                    total += c
                    src = _gcov_source_path(gcov_path)
                    if src:
                        paths.append(src)
        return counts, total, paths

    if not os.path.exists(diff_dir):
        return ExtractionResult(
            success=False,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=f"Diff directory does not exist: {diff_dir}"
        )

    # Get all diff files
    diff_files = [f for f in os.listdir(diff_dir)
                  if os.path.isfile(os.path.join(diff_dir, f))]

    if not diff_files:
        # An empty diff set is a VALID analytical outcome: the feature toggle
        # produced no line-level differences in files common to both builds.
        # This happens when a feature is implemented as dedicated source files
        # (which appear only in the enabled build and are tracked separately as
        # feature_only_files) rather than as #ifdef-interleaved code in shared
        # files. Report 0 removable lines rather than failing the workflow.
        print(f"[+] No non-empty diffs in {diff_dir} — 0 interleaved removable lines")
        fo_counts, fo_total, fo_paths = _count_feature_only()
        if fo_total:
            print(f"[+] Paper-aligned feature-only files: {fo_total} lines "
                  f"across {len(fo_counts)} dedicated file(s)")
        return ExtractionResult(
            success=True,
            file_line_counts={},
            total_removable_lines=0,
            file_line_numbers={},
            file_line_content={},
            error_message=None,
            feature_only_file_counts=fo_counts,
            feature_only_removable_lines=fo_total,
            total_feature_lines=fo_total,
            feature_only_source_paths=fo_paths,
        )

    # Data structures to store results
    file_line_counts = {}
    file_line_numbers = {}
    file_line_content = {}
    total_lines = 0

    # Process each diff file
    for diff_file in diff_files:
        file_path = os.path.join(diff_dir, diff_file)

        # Extract base filename (remove .gcov extension)
        # Format: filename.c.gcov -> filename.c
        file_name = diff_file
        if file_name.endswith('.gcov'):
            file_name = file_name[:-5]  # Remove .gcov

        # Skip IDL-compiler-generated files (mechanical churn, not feature source).
        if _is_generated_idl(file_name):
            continue

        # Parse the diff file
        line_numbers = []
        line_contents = []

        try:
            with open(file_path, encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Look for ##### markers (never-executed code)
                    # Exclude /*EOF*/ markers
                    if '#####' in line and '/*EOF*/' not in line:
                        # Extract line number: format is "    #####:  123:code"
                        match = re.search(r'(\d+):', line)
                        if match:
                            line_num = int(match.group(1))
                            line_numbers.append(line_num)

                        # Extract source code content
                        # Format: "    #####:  123:source code here"
                        match = re.search(r'\d+:(.*)', line)
                        if match:
                            source = match.group(1)
                            # Escape quotes for later use
                            source = source.replace('"', '\\"')
                            line_contents.append(source)
        except Exception as e:
            print(f"[-] Error parsing {diff_file}: {e}")
            continue

        # Store results if we found removable lines
        if line_numbers:
            count = len(line_numbers)
            file_line_counts[file_name] = count
            file_line_numbers[file_name] = line_numbers
            file_line_content[file_name] = line_contents
            total_lines += count

            print("\n------------------")
            print(f"Lines to remove from {file_name}")
            print("------------------")
            print(f"Count: {count}")

    print("\n------------------")
    print(f"Total lines to remove: {total_lines}")
    print("------------------")

    # Print summary
    for file_name, line_nums in file_line_numbers.items():
        print(f"\t{file_name}: {line_nums}")

    fo_counts, fo_total, fo_paths = _count_feature_only()
    if fo_total:
        print(f"[+] Paper-aligned feature-only files: {fo_total} lines "
              f"across {len(fo_counts)} dedicated file(s)")

    return ExtractionResult(
        success=True,
        file_line_counts=file_line_counts,
        total_removable_lines=total_lines,
        file_line_numbers=file_line_numbers,
        file_line_content=file_line_content,
        error_message=None,
        feature_only_file_counts=fo_counts,
        feature_only_removable_lines=fo_total,
        total_feature_lines=total_lines + fo_total,
        feature_only_source_paths=fo_paths,
    )
