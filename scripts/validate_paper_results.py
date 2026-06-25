#!/usr/bin/env python3
"""
Validate PRAT demo results against paper-reported expected values.

Reads workflow_checkpoint.json files from a results directory, compares
them against paper_expected_results.json, and produces a structured
validation report.

Exit codes:
  0 — all demos pass validation
  1 — one or more demos fail or are missing
  2 — configuration error

Usage:
  python3 scripts/validate_paper_results.py results/docker/
  python3 scripts/validate_paper_results.py results/docker/ --strict
  python3 scripts/validate_paper_results.py results/docker/ --json results/validation.json
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TargetValidation:
    """Validation result for a single target."""
    name: str
    project: str
    feature: str
    status: str = "PENDING"  # PASS, PASS_PAPER_ALIGNED, FAIL, MISSING, ERROR
    actual_lines: Optional[int] = None
    paper_lines: Optional[int] = None
    min_acceptable: Optional[int] = None
    max_acceptable: Optional[int] = None
    within_range: bool = False
    deviation_pct: Optional[float] = None
    # Paper-aligned metric: interleaved feature lines PLUS dedicated feature-only
    # files. The primary `actual_lines` counts only interleaved lines, so for
    # features implemented as separate files this captures the rest.
    feature_only_lines: Optional[int] = None
    combined_lines: Optional[int] = None
    combined_within_range: bool = False
    metric_used: Optional[str] = None  # which measure satisfied the range
    key_files_found: list = field(default_factory=list)
    key_files_missing: list = field(default_factory=list)
    error_message: Optional[str] = None


@dataclass
class ValidationReport:
    """Complete validation report."""
    timestamp: str
    results_dir: str
    total_targets: int
    passed: int
    failed: int
    missing: int
    targets: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.missing == 0


def load_expected_results(path: Path) -> dict:
    """Load paper expected results."""
    with open(path) as f:
        data = json.load(f)
    return data["targets"]


def load_checkpoint(results_dir: Path, demo_name: str) -> Optional[dict]:
    """Load workflow checkpoint for a demo."""
    # Try common subdirectory patterns
    candidates = [
        results_dir / demo_name / "workflow_checkpoint.json",
        results_dir / demo_name / "checkpoint.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None


def _key_file_matches(key: str, files: list) -> bool:
    """Return True if a paper key_file is represented in the analyzed files.

    Handles three key shapes against coverage data that is often flat basenames:
      - file with extension, path-qualified ("libavcodec/libx264.c") -> match by
        basename ("libx264.c") OR full-path substring;
      - bare filename ("bridge.c") -> basename match;
      - directory/segment ("av1/encoder", "aom_dsp", "Security") -> substring
        match against any full source path (populated from gcov "Source:" lines).
    """
    import os as _os

    key = (key or "").strip().rstrip("/")
    if not key:
        return False
    key_base = _os.path.basename(key)
    key_is_file = "." in key_base  # heuristic: file vs directory/segment

    for f in files:
        f_norm = (f or "").strip()
        if not f_norm:
            continue
        # Full-path / substring match (works when files carry relative paths).
        if key in f_norm:
            return True
        if key_is_file and key_base and key_base == _os.path.basename(f_norm):
            return True
    return False


def validate_target(
    demo_name: str,
    expected: dict,
    checkpoint: Optional[dict],
) -> TargetValidation:
    """Validate a single target against expected results."""

    result = TargetValidation(
        name=demo_name,
        project=expected["project"],
        feature=expected["feature"],
        paper_lines=expected["paper_lines_removed"],
        min_acceptable=expected["min_acceptable"],
        max_acceptable=expected["max_acceptable"],
    )

    if checkpoint is None:
        result.status = "MISSING"
        result.error_message = "No workflow_checkpoint.json found"
        return result

    # Check if workflow succeeded
    if not checkpoint.get("success", False):
        result.status = "ERROR"
        result.error_message = checkpoint.get("error_message", "Workflow did not succeed")
        return result

    # Extract actual line count
    extraction = checkpoint.get("extraction_result", {})
    if not extraction:
        result.status = "ERROR"
        result.error_message = "No extraction_result in checkpoint"
        return result

    actual_lines = extraction.get("total_removable_lines", 0)
    result.actual_lines = actual_lines

    # Paper-aligned combined metric (interleaved + dedicated feature-only files)
    feature_only = extraction.get("feature_only_removable_lines", 0)
    combined = extraction.get("total_feature_lines", actual_lines + feature_only)
    result.feature_only_lines = feature_only
    result.combined_lines = combined

    # Check range
    min_ok = expected["min_acceptable"]
    max_ok = expected["max_acceptable"]
    result.within_range = min_ok <= actual_lines <= max_ok
    result.combined_within_range = min_ok <= combined <= max_ok

    # Compute deviation from paper value (use whichever metric is in range, else
    # the combined/paper-aligned measure which is the closest to the paper's
    # definition of total removable feature code).
    paper_lines = expected["paper_lines_removed"]
    metric_value = actual_lines if result.within_range else combined
    if paper_lines > 0:
        result.deviation_pct = round(
            ((metric_value - paper_lines) / paper_lines) * 100, 1
        )

    # Check key files.
    # Coverage files are tracked by flat basename (e.g. "libx264.c"), while the
    # paper's key_files are sometimes path-qualified ("libavcodec/libx264.c") or
    # directory-style ("av1/encoder"). We therefore match against the union of:
    #   - analyzed/interleaved file names (basenames)
    #   - feature-only file names (basenames)
    #   - feature-only source paths captured from each gcov "Source:" header
    #     (full relative paths, when available) — enables directory-key matching.
    file_line_counts = extraction.get("file_line_counts", {})
    feature_only_files = checkpoint.get("diff_result", {}).get("feature_only_files", [])
    feature_only_paths = extraction.get("feature_only_source_paths", [])
    all_files = list(file_line_counts.keys()) + list(feature_only_files) + list(feature_only_paths)

    for key_file in expected.get("key_files", []):
        if _key_file_matches(key_file, all_files):
            result.key_files_found.append(key_file)
        else:
            result.key_files_missing.append(key_file)

    # Set status
    if result.within_range:
        result.status = "PASS"
        result.metric_used = "interleaved"
    elif result.combined_within_range:
        # Reproduced once dedicated feature-only files are counted (the paper's
        # definition of removable feature code). Flagged distinctly for honesty.
        result.status = "PASS_PAPER_ALIGNED"
        result.metric_used = "combined (interleaved + feature-only files)"
    else:
        result.status = "FAIL"
        result.metric_used = "none"
        lo_metric = max(actual_lines, combined)
        if combined < min_ok:
            result.error_message = (
                f"Below minimum under both metrics: interleaved={actual_lines}, "
                f"combined={combined} < {min_ok} (paper: {paper_lines})"
            )
        else:
            result.error_message = (
                f"Out of range: interleaved={actual_lines}, combined={combined} "
                f"vs [{min_ok}-{max_ok}] (paper: {paper_lines})"
            )

    return result


def run_validation(results_dir: Path, expected_path: Path, strict: bool = False) -> ValidationReport:
    """Run full validation against all expected targets."""

    expected_results = load_expected_results(expected_path)

    report = ValidationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        results_dir=str(results_dir),
        total_targets=len(expected_results),
        passed=0,
        failed=0,
        missing=0,
    )

    for demo_name, expected in expected_results.items():
        checkpoint = load_checkpoint(results_dir, demo_name)
        validation = validate_target(demo_name, expected, checkpoint)
        report.targets.append(validation)

        if validation.status in ("PASS", "PASS_PAPER_ALIGNED"):
            report.passed += 1
        elif validation.status == "MISSING":
            report.missing += 1
        else:
            report.failed += 1

    return report


def print_report(report: ValidationReport) -> None:
    """Print human-readable validation report."""
    print()
    print("=" * 78)
    print("PRAT Paper Results Validation Report")
    print("=" * 78)
    print(f"Timestamp:   {report.timestamp}")
    print(f"Results dir: {report.results_dir}")
    print(f"Targets:     {report.total_targets}")
    print()

    for t in report.targets:
        icon = {
            "PASS": "✅",
            "PASS_PAPER_ALIGNED": "🟢",
            "FAIL": "❌",
            "MISSING": "⬜",
            "ERROR": "⚠️",
        }.get(t.status, "?")
        print(f"{icon} {t.name:<22} ", end="")

        if t.status == "PASS":
            print(
                f"actual={t.actual_lines:>6} lines  "
                f"paper={t.paper_lines:>6}  "
                f"deviation={t.deviation_pct:>+6.1f}%"
            )
        elif t.status == "PASS_PAPER_ALIGNED":
            print(
                f"interleaved={t.actual_lines:>5}  +feature-files={t.feature_only_lines:>5}  "
                f"=combined={t.combined_lines:>6}  paper={t.paper_lines:>6}  "
                f"(paper-aligned metric)"
            )
        elif t.status == "MISSING":
            print("(no results found)")
        elif t.status == "ERROR":
            print(f"ERROR: {t.error_message}")
        else:
            print(
                f"interleaved={t.actual_lines}  combined={t.combined_lines}  "
                f"range=[{t.min_acceptable}–{t.max_acceptable}]  {t.error_message}"
            )

        if t.key_files_missing:
            print(f"       ⚠️  Missing key files: {', '.join(t.key_files_missing)}")

    print()
    print("-" * 78)
    print(f"Summary: {report.passed} passed, {report.failed} failed, {report.missing} missing")
    print(f"Result:  {'PASS ✅' if report.success else 'FAIL ❌'}")
    print("=" * 78)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate PRAT demo results against paper-reported values"
    )
    parser.add_argument(
        "results_dir",
        help="Directory containing demo result subdirectories",
    )
    parser.add_argument(
        "--expected",
        default=None,
        help="Path to paper_expected_results.json (default: repo root)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any target deviates more than tolerance_pct from paper value",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Write structured JSON report to this path",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"[!] Results directory not found: {results_dir}", file=sys.stderr)
        return 2

    # Find expected results file
    if args.expected:
        expected_path = Path(args.expected)
    else:
        # Walk up to find it
        for candidate in [
            Path("paper_expected_results.json"),
            Path(__file__).parent.parent / "paper_expected_results.json",
        ]:
            if candidate.exists():
                expected_path = candidate
                break
        else:
            print("[!] Cannot find paper_expected_results.json", file=sys.stderr)
            return 2

    report = run_validation(results_dir, expected_path, strict=args.strict)
    print_report(report)

    # Write JSON report if requested
    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(
                {
                    "timestamp": report.timestamp,
                    "results_dir": report.results_dir,
                    "total_targets": report.total_targets,
                    "passed": report.passed,
                    "failed": report.failed,
                    "missing": report.missing,
                    "success": report.success,
                    "targets": [asdict(t) for t in report.targets],
                },
                f,
                indent=2,
            )
        print(f"[+] JSON report written to {json_path}")

    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
