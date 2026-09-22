#!/usr/bin/env python3
"""
Compare PRAT compatibility-demo results with paper-reported values.

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
import hashlib
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
    status: str = "PENDING"  # COMPATIBLE, OBSERVED, FAIL, MISSING, ERROR
    actual_lines: Optional[int] = None
    paper_lines: Optional[int] = None
    min_acceptable: Optional[int] = None
    max_acceptable: Optional[int] = None
    within_range: bool = False
    deviation_pct: Optional[float] = None
    # `actual_lines` is |D_f| across shared and dedicated feature files.
    feature_only_lines: Optional[int] = None
    combined_lines: Optional[int] = None
    combined_within_range: bool = False
    metric_used: Optional[str] = None  # which measure satisfied the range
    analyzed_feature: Optional[str] = None  # set when a substitute feature was analyzed
    # False when the paper never analyzed this feature, so there is no value to
    # reproduce and the measurement is reported for information only.
    paper_feature: bool = True
    paper_source: Optional[str] = None
    paper_lines_manual: Optional[int] = None
    key_files_found: list = field(default_factory=list)
    key_files_missing: list = field(default_factory=list)
    provenance_errors: list[str] = field(default_factory=list)
    evidence_errors: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    structural_lines_absorbed: int = 0
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
    #: Targets measured but not scored, because the paper publishes no value for
    #: the feature they analyze.
    observed: int = 0
    targets: list = field(default_factory=list)

    @property
    def comparable_targets(self) -> int:
        """Targets that have a published paper value to compare against."""
        return self.passed + self.failed

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.missing == 0


def load_expected_results(path: Path) -> dict:
    """Load the demo targets, skipping the file's metadata keys."""
    with open(path) as f:
        data = json.load(f)
    targets = data["targets"]
    expected_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    repo_root = path.resolve().parent
    results = {}
    for name, spec in targets.items():
        if name.startswith("_"):
            continue
        item = dict(spec)
        item["_expected_results_sha256"] = expected_digest
        docker_demo = item.get("docker_demo")
        dockerfile = repo_root / "docker" / str(docker_demo) / "Dockerfile"
        if dockerfile.is_file():
            item["_dockerfile_sha256"] = hashlib.sha256(
                dockerfile.read_bytes()
            ).hexdigest()
        results[name] = item
    return results


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


def load_json_if_present(path: Path) -> Optional[dict]:
    """Load a JSON artifact when present and structurally valid."""
    if not path.exists():
        return None
    try:
        with open(path) as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_result_bundle(results_dir: Path, demo_name: str) -> tuple[
    Optional[dict], Optional[dict], Optional[dict]
]:
    """Load checkpoint, in-container manifest, and host-run manifest."""
    directory = results_dir / demo_name
    demo_manifest = load_json_if_present(directory / "demo_manifest.json")
    if demo_manifest is not None:
        integrity_errors = []
        hashes = demo_manifest.get("artifact_sha256")
        if not isinstance(hashes, dict) or not hashes:
            integrity_errors.append("host manifest has no artifact hash inventory")
        else:
            for relative, expected_digest in hashes.items():
                artifact = directory / relative
                if not artifact.is_file():
                    integrity_errors.append(f"hashed artifact is missing: {relative}")
                    continue
                actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
                if actual != expected_digest:
                    integrity_errors.append(f"artifact hash mismatch: {relative}")
        demo_manifest["_integrity_errors"] = integrity_errors
    return (
        load_checkpoint(results_dir, demo_name),
        load_json_if_present(directory / "manifest.json"),
        demo_manifest,
    )


def _same_name(actual: object, expected: object) -> bool:
    """Compare project/feature identifiers without case or punctuation noise."""
    def normalize(value: object) -> str:
        return "".join(
            char for char in str(value or "").lower() if char.isalnum()
        )

    return bool(normalize(actual)) and normalize(actual) == normalize(expected)


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
    manifest: Optional[dict] = None,
    demo_manifest: Optional[dict] = None,
    strict: bool = False,
) -> TargetValidation:
    """Validate a single target against the paper.

    A target with ``paper_lines_removed: null`` has no published value for the
    feature it analyzes. Such a target is reported as OBSERVED: the measurement
    is printed, but it is neither a pass nor a failure against the paper, because
    there is nothing to compare it to. Inventing a range for those targets is
    what made earlier reports look like failed reproductions.
    """
    result = TargetValidation(
        name=demo_name,
        project=expected["project"],
        feature=expected["feature"],
        paper_lines=expected.get("paper_lines_removed"),
        paper_lines_manual=expected.get("paper_lines_manual"),
        min_acceptable=expected.get("min_acceptable"),
        max_acceptable=expected.get("max_acceptable"),
        paper_feature=bool(expected.get("paper_feature", True)),
        paper_source=expected.get("paper_source"),
    )
    result.provenance = {
        "expected_source_commit": expected.get("commit"),
        "expected_results_sha256": expected.get("_expected_results_sha256"),
        "dockerfile_sha256": expected.get("_dockerfile_sha256"),
    }

    analyzed = expected.get("analyzed_feature")
    if analyzed and analyzed != expected["feature"]:
        result.analyzed_feature = analyzed

    if checkpoint is None:
        result.status = "MISSING"
        result.error_message = "No workflow_checkpoint.json found"
        return result
    result.provenance["checkpoint_run_id"] = checkpoint.get("run_id")

    if not _same_name(checkpoint.get("feature"), expected["feature"]):
        result.provenance_errors.append(
            f"checkpoint feature {checkpoint.get('feature')!r} does not match "
            f"{expected['feature']!r}"
        )
    expected_project_id = expected.get("project_id", expected["project"])
    if not _same_name(checkpoint.get("project"), expected_project_id):
        result.provenance_errors.append(
            f"checkpoint project {checkpoint.get('project')!r} does not match "
            f"{expected_project_id!r}"
        )

    if manifest is None:
        result.provenance_errors.append("missing in-container manifest.json")
    else:
        result.provenance.update({
            "source_commit": manifest.get("project_git_commit"),
            "container_run_id": manifest.get("run_id"),
            "build_system": manifest.get("build_system"),
        })
        if not _same_name(manifest.get("feature"), expected["feature"]):
            result.provenance_errors.append("manifest feature does not match target")
        if not _same_name(manifest.get("project_name"), expected_project_id):
            result.provenance_errors.append("manifest project does not match target")
        actual_commit = manifest.get("project_git_commit")
        expected_commit = expected.get("commit")
        if not actual_commit:
            result.provenance_errors.append("manifest has no source commit")
        elif expected_commit and actual_commit != expected_commit:
            result.provenance_errors.append(
                f"source commit {actual_commit} does not match pinned "
                f"commit {expected_commit}"
            )
        if manifest.get("success") is not True:
            result.evidence_errors.append("manifest does not record workflow success")
        expected_build_system = expected.get("build_system")
        if (
            expected_build_system
            and manifest.get("build_system") != expected_build_system
        ):
            result.provenance_errors.append(
                f"manifest build system {manifest.get('build_system')!r} does "
                f"not match {expected_build_system!r}"
            )

    if demo_manifest is None:
        result.provenance_errors.append("missing host demo_manifest.json")
    elif manifest is not None:
        result.provenance["host_run_id"] = demo_manifest.get("run_id")
        if isinstance(demo_manifest.get("provenance"), dict):
            result.provenance["host"] = dict(demo_manifest["provenance"])
        host_run = demo_manifest.get("run_id")
        target_run = manifest.get("run_id")
        if not host_run or not target_run or host_run != target_run:
            result.provenance_errors.append("host/container run IDs do not match")
        checkpoint_run = checkpoint.get("run_id")
        if not checkpoint_run or checkpoint_run != target_run:
            result.provenance_errors.append(
                "checkpoint/container run IDs do not match"
            )
        result.provenance_errors.extend(
            demo_manifest.get("_integrity_errors", [])
        )
        provenance = demo_manifest.get("provenance")
        if not isinstance(provenance, dict):
            result.provenance_errors.append("host manifest has no provenance envelope")
        else:
            required = (
                "prat_git_commit",
                "prat_source_sha256",
                "dockerfile_sha256",
                "expected_results_sha256",
                "image_id",
            )
            for field_name in required:
                if not provenance.get(field_name):
                    result.provenance_errors.append(
                        f"host provenance has no {field_name}"
                    )
            expected_results_digest = expected.get("_expected_results_sha256")
            if (
                expected_results_digest
                and provenance.get("expected_results_sha256")
                != expected_results_digest
            ):
                result.provenance_errors.append(
                    "expected-results digest does not match validator input"
                )
            expected_dockerfile = expected.get("_dockerfile_sha256")
            if (
                expected_dockerfile
                and provenance.get("dockerfile_sha256") != expected_dockerfile
            ):
                result.provenance_errors.append(
                    "Dockerfile digest does not match validator checkout"
                )

    if not checkpoint.get("success", False):
        result.status = "ERROR"
        result.error_message = checkpoint.get(
            "error_message", "Workflow did not succeed"
        )
        return result

    extraction = checkpoint.get("extraction_result") or {}
    if not extraction:
        result.status = "ERROR"
        result.error_message = "No extraction_result in checkpoint"
        return result
    actual_lines = int(extraction.get("total_removable_lines", 0))

    for side in ("coverage_enabled", "coverage_disabled"):
        coverage = checkpoint.get(side)
        if not isinstance(coverage, dict):
            result.evidence_errors.append(f"{side} evidence is missing")
            continue
        if coverage.get("dynamic_execution") is not True:
            result.evidence_errors.append(f"{side} was not dynamically executed")
        if (
            int(coverage.get("execution_succeeded", 0))
            + int(coverage.get("symbolic_tests_replayed", 0))
            < 1
        ):
            result.evidence_errors.append(
                f"{side} has no successful execution evidence"
            )
        if coverage.get("execution_failed", 0):
            result.evidence_errors.append(f"{side} contains failed test commands")
        if coverage.get("execution_timed_out", 0):
            result.evidence_errors.append(f"{side} contains timed-out test commands")

    if strict:
        removal = checkpoint.get("removal_result")
        verification = checkpoint.get("verification_result")
        if not isinstance(removal, dict) or removal.get("success") is not True:
            result.evidence_errors.append(
                "strict validation requires successful source removal"
            )
        elif (
            removal.get("lines_removed") != actual_lines
            or removal.get("target_lines") not in (None, actual_lines)
            or removal.get("missing_source_files")
            or removal.get("skipped_unbalanced")
        ):
            result.evidence_errors.append(
                "removal accounting does not match the complete mapped set"
            )
        elif int(removal.get("absorbed_structural", 0)) < 0:
            result.evidence_errors.append(
                "removal structural-line accounting is invalid"
            )
        elif isinstance(removal, dict):
            result.structural_lines_absorbed = int(
                removal.get("absorbed_structural", 0)
            )
        if (
            not isinstance(verification, dict)
            or verification.get("success") is not True
            or verification.get("status") not in ("passed", "VerificationStatus.PASSED")
        ):
            result.evidence_errors.append(
                "strict validation requires successful post-removal verification"
            )
        elif (
            verification.get("compiles") is not True
            or int(verification.get("total_tests_run", 0)) < 1
            or int(verification.get("total_tests_failed", 0)) != 0
            or verification.get("crashes")
            or verification.get("diverged_suites")
        ):
            result.evidence_errors.append(
                "post-removal verification evidence is incomplete"
            )

    # |D_f| is a single figure now: interleaved and dedicated-feature-file lines
    # are two partitions of the same set difference, not two competing metrics.
    feature_only = extraction.get("feature_only_removable_lines", 0)
    result.actual_lines = actual_lines
    result.feature_only_lines = feature_only
    result.combined_lines = actual_lines
    result.metric_used = "|D_f|"

    # Key files.
    file_line_counts = extraction.get("file_line_counts", {})
    feature_only_paths = extraction.get("feature_only_source_paths", [])
    all_files = list(file_line_counts.keys()) + list(feature_only_paths)

    for key_file in expected.get("key_files", []):
        if _key_file_matches(key_file, all_files):
            result.key_files_found.append(key_file)
        else:
            result.key_files_missing.append(key_file)

    if result.key_files_missing:
        result.evidence_errors.append(
            f"missing expected source evidence: {', '.join(result.key_files_missing)}"
        )

    paper_lines = result.paper_lines

    if paper_lines is None:
        # No published value for this feature. Report the measurement; do not
        # score it against a number the paper never gave.
        result.status = (
            "ERROR"
            if result.provenance_errors or result.evidence_errors
            else "OBSERVED"
        )
        result.within_range = True
        result.combined_within_range = True
        if result.status == "ERROR":
            result.error_message = "; ".join(
                result.provenance_errors + result.evidence_errors
            )
        return result

    min_ok = result.min_acceptable
    max_ok = result.max_acceptable
    if min_ok is None or max_ok is None:
        result.within_range = True
        result.combined_within_range = True
        if paper_lines > 0:
            result.deviation_pct = round(
                ((actual_lines - paper_lines) / paper_lines) * 100, 1
            )
            if actual_lines == 0:
                result.evidence_errors.append(
                    "zero mapped lines cannot reproduce a nonzero paper result"
                )
        if result.provenance_errors or result.evidence_errors:
            result.status = "FAIL"
            result.error_message = "; ".join(
                result.provenance_errors + result.evidence_errors
            )
        else:
            result.status = "COMPATIBLE"
        return result

    result.within_range = min_ok <= actual_lines <= max_ok
    result.combined_within_range = result.within_range

    if paper_lines > 0:
        result.deviation_pct = round(
            ((actual_lines - paper_lines) / paper_lines) * 100, 1
        )

    if paper_lines > 0 and actual_lines == 0:
        result.within_range = False
        result.combined_within_range = False
        result.evidence_errors.append(
            "zero mapped lines cannot reproduce a nonzero paper result"
        )

    if strict and paper_lines > 0:
        tolerance = expected.get("tolerance_pct")
        if tolerance is None or result.deviation_pct is None:
            result.evidence_errors.append("strict tolerance is not configured")
        elif abs(result.deviation_pct) > float(tolerance):
            result.within_range = False
            result.combined_within_range = False
            result.evidence_errors.append(
                f"deviation {result.deviation_pct:+.1f}% exceeds "
                f"strict tolerance {float(tolerance):.1f}%"
            )

    if (
        result.within_range
        and not result.provenance_errors
        and not result.evidence_errors
    ):
        result.status = "COMPATIBLE"
    else:
        result.status = "FAIL"
        messages = result.provenance_errors + result.evidence_errors
        if not result.within_range:
            direction = "below" if actual_lines < min_ok else "above"
            messages.append(
                f"|D_f|={actual_lines} is {direction} the accepted range "
                f"[{min_ok}-{max_ok}] for paper value {paper_lines}"
            )
        result.error_message = "; ".join(messages)

    return result


def run_validation(
    results_dir: Path,
    expected_path: Path,
    strict: bool = False,
    target_names: list[str] | None = None,
) -> ValidationReport:
    """Run full validation against all expected targets."""

    expected_results = load_expected_results(expected_path)
    if target_names:
        unknown = sorted(set(target_names) - set(expected_results))
        if unknown:
            raise ValueError(f"Unknown target(s): {', '.join(unknown)}")
        expected_results = {
            name: expected_results[name] for name in target_names
        }

    report = ValidationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        results_dir=str(results_dir),
        total_targets=len(expected_results),
        passed=0,
        failed=0,
        missing=0,
    )

    for demo_name, expected in expected_results.items():
        checkpoint, manifest, demo_manifest = load_result_bundle(
            results_dir, demo_name
        )
        validation = validate_target(
            demo_name,
            expected,
            checkpoint,
            manifest=manifest,
            demo_manifest=demo_manifest,
            strict=strict,
        )
        report.targets.append(validation)

        if validation.status == "COMPATIBLE":
            report.passed += 1
        elif validation.status == "OBSERVED":
            report.observed += 1
        elif validation.status == "MISSING":
            report.missing += 1
        else:
            report.failed += 1

    return report


def print_report(report: ValidationReport) -> None:
    """Print human-readable validation report."""
    print()
    print("=" * 78)
    print("PRAT Paper-Value Compatibility Report")
    print("=" * 78)
    print(f"Timestamp:   {report.timestamp}")
    print(f"Results dir: {report.results_dir}")
    print(f"Targets:     {report.total_targets}")
    print()

    for t in report.targets:
        icon = {
            "COMPATIBLE": "[ OK  ]",
            "OBSERVED": "[OBS ]",
            "FAIL": "[FAIL]",
            "MISSING": "[    ]",
            "ERROR": "[ERR ]",
        }.get(t.status, "[  ? ]")
        print(f"{icon} {t.name:<32} ", end="")

        if t.status == "COMPATIBLE":
            manual = ""
            if t.paper_lines_manual is not None:
                manual = f"  paper-manual={t.paper_lines_manual}"
            deviation = (
                f"  deviation={t.deviation_pct:>+7.1f}%"
                if t.deviation_pct is not None
                else ""
            )
            print(
                f"|D_f|={t.actual_lines:>6}  paper={t.paper_lines:>6}"
                f"{deviation}{manual}"
            )
        elif t.status == "OBSERVED":
            print(f"|D_f|={t.actual_lines:>6}  (no paper value for this feature)")
        elif t.status == "MISSING":
            print("(no results found)")
        elif t.status == "ERROR":
            print(f"ERROR: {t.error_message}")
        else:
            print(f"|D_f|={t.actual_lines}  {t.error_message}")

        if t.status == "OBSERVED" and t.paper_source:
            print(f"        note: {t.paper_source}")
        if t.feature_only_lines:
            print(f"        of which {t.feature_only_lines} line(s) are in "
                  f"dedicated feature file(s)")
        if t.key_files_missing:
            print(f"        missing key files: {', '.join(t.key_files_missing)}")
        for error in t.provenance_errors:
            print(f"        provenance: {error}")
        for error in t.evidence_errors:
            print(f"        evidence: {error}")
        if t.analyzed_feature:
            print(f"        analyzed '{t.analyzed_feature}' rather than "
                  f"'{t.feature}' — see notes in paper_expected_results.json")

    print()
    print("-" * 78)
    print(f"Published-value targets:  {report.passed} evidence-compatible, "
          f"{report.failed} failed  (of {report.comparable_targets})")
    if report.observed:
        print(f"Measured, not scored:     {report.observed} target(s) analyze a "
              f"feature the paper reports no line count for")
    if report.missing:
        print(f"Missing results:          {report.missing}")
    print(f"Result:  {'PASS' if report.success else 'FAIL'}")
    print("=" * 78)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare PRAT compatibility demos with paper-reported values"
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
        help="Require successful exact removal and post-removal verification",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="Validate only this target; may be repeated",
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

    try:
        report = run_validation(
            results_dir,
            expected_path,
            strict=args.strict,
            target_names=args.target,
        )
    except ValueError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
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
                    "observed": report.observed,
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
