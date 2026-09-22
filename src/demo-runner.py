#!/usr/bin/env python3
"""
PRAT Demo Runner

This script orchestrates building and running Docker-based PRAT demos,
validates results against expected values, and generates comparison reports.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add prat module to path
sys.path.insert(0, str(Path(__file__).parent))

from prat.docker_runner import (
    build_docker_image,
    check_docker_available,
    remove_docker_image,
    run_docker_container,
)


@dataclass
class ExpectedResult:
    """Expected results for a demo."""
    min_removable_lines: Optional[int]
    max_removable_lines: Optional[int]
    key_files: list[str]
    description: str
    paper_lines: Optional[int] = None

    @property
    def is_scored(self) -> bool:
        """Whether a numerical compatibility range is configured."""
        return (
            self.min_removable_lines is not None
            and self.max_removable_lines is not None
        )

    @property
    def has_paper_value(self) -> bool:
        return self.paper_lines is not None


@dataclass
class DemoResult:
    """Result of running a demo."""
    demo_name: str
    success: bool
    removable_lines: Optional[int]
    files_analyzed: Optional[int]
    key_files_found: list[str]
    key_files_missing: list[str]
    within_expected_range: bool
    execution_time: Optional[float]
    error_message: Optional[str] = None
    workflow_success: bool = False


# Expected results for each demo.
#
# SINGLE SOURCE OF TRUTH: paper references/key-files are loaded from
# paper_expected_results.json (the same file the validator uses) so the demo
# runner and `scripts/validate_paper_results.py` cannot disagree.
_PAPER_EXPECTED_PATH = Path(__file__).resolve().parent.parent / "paper_expected_results.json"


def _load_expected_results() -> dict[str, ExpectedResult]:
    """Build EXPECTED_RESULTS from paper_expected_results.json (authoritative)."""
    try:
        with open(_PAPER_EXPECTED_PATH) as f:
            targets = json.load(f)["targets"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"Cannot load authoritative demo expectations from "
            f"{_PAPER_EXPECTED_PATH}: {exc}"
        ) from exc

    results: dict[str, ExpectedResult] = {}
    for name, spec in targets.items():
        if name.startswith("_") or not isinstance(spec, dict):
            continue
        results[name] = ExpectedResult(
            min_removable_lines=spec.get("min_acceptable"),
            max_removable_lines=spec.get("max_acceptable"),
            key_files=spec.get("key_files", []),
            description=f"{spec.get('project', name)} {spec.get('feature', '')} feature analysis".strip(),
            paper_lines=spec.get("paper_lines_removed"),
        )
    return results


EXPECTED_RESULTS = _load_expected_results()


# Demo configurations
DEMO_CONFIGS = {
    "mosquitto-tls": {
        "dockerfile": "docker/demo1/Dockerfile",
        "image_name": "prat-demo:mosquitto-tls",
        "feature": "TLS",
        "project": "mosquitto"
    },
    "mosquitto-bridge": {
        "dockerfile": "docker/demo2/Dockerfile",
        "image_name": "prat-demo:mosquitto-bridge",
        "feature": "BRIDGE",
        "project": "mosquitto"
    },
    # The "feature" here must be the option the Dockerfile CMD actually passes,
    # otherwise demo_manifest.json records a feature that was never analyzed.
    "ffmpeg-dca": {
        "dockerfile": "docker/demo3/Dockerfile",
        "image_name": "prat-demo:ffmpeg-dca",
        "feature": "decoder=dca",
        "project": "ffmpeg"
    },
    "uamqp-websockets": {
        "dockerfile": "docker/demo4/Dockerfile",
        "image_name": "prat-demo:uamqp-websockets",
        "feature": "use_wsio",
        "project": "azure-uamqp-c"
    },
    "opendds-content-filtered-topic": {
        "dockerfile": "docker/demo5/Dockerfile",
        "image_name": "prat-demo:opendds-content-filtered-topic",
        "feature": "content-filtered-topic",
        "project": "opendds"
    },
    "quiche-qlog": {
        "dockerfile": "docker/demo6/Dockerfile",
        "image_name": "prat-demo:quiche-qlog",
        "feature": "qlog",
        "project": "quiche"
    },
    "rav1e-serialize": {
        "dockerfile": "docker/demo8/Dockerfile",
        "image_name": "prat-demo:rav1e-serialize",
        "feature": "serialize",
        "project": "rav1e",
    },
    "aom-encoder": {
        "dockerfile": "docker/demo7/Dockerfile",
        "image_name": "prat-demo:aom-encoder",
        "feature": "CONFIG_AV1_ENCODER",
        "project": "aom"
    },
}

_missing_expectations = sorted(set(DEMO_CONFIGS) - set(EXPECTED_RESULTS))
if _missing_expectations:
    raise RuntimeError(
        "Demo configuration has no authoritative expectation: "
        + ", ".join(_missing_expectations)
    )


def build_demo(demo_name: str, no_cache: bool = False) -> bool:
    """
    Build Docker image for a demo.

    Args:
        demo_name: Name of demo to build
        no_cache: If True, build without cache

    Returns:
        True if build successful
    """
    if demo_name not in DEMO_CONFIGS:
        print(f"[!] Unknown demo: {demo_name}")
        print(f"[!] Available demos: {', '.join(DEMO_CONFIGS.keys())}")
        return False

    config = DEMO_CONFIGS[demo_name]

    print(f"\n{'='*70}")
    print(f"Building Demo: {demo_name}")
    print(f"{'='*70}")

    success = build_docker_image(
        dockerfile_path=config["dockerfile"],
        image_name=config["image_name"],
        build_context=".",
        no_cache=no_cache
    )

    if success:
        print(f"[+] Successfully built {demo_name}")
    else:
        print(f"[!] Failed to build {demo_name}")

    return success


def run_demo(demo_name: str, output_dir: str) -> DemoResult:
    """
    Run a demo and collect results.

    Args:
        demo_name: Name of demo to run
        output_dir: Directory to store output

    Returns:
        DemoResult with execution results
    """
    if demo_name not in DEMO_CONFIGS:
        return DemoResult(
            demo_name=demo_name,
            success=False,
            removable_lines=None,
            files_analyzed=None,
            key_files_found=[],
            key_files_missing=[],
            within_expected_range=False,
            execution_time=None,
            error_message=f"Unknown demo: {demo_name}"
        )

    config = DEMO_CONFIGS[demo_name]
    expected = EXPECTED_RESULTS[demo_name]

    print(f"\n{'='*70}")
    print(f"Running Demo: {demo_name}")
    print(f"{'='*70}")
    print(f"Description: {expected.description}")
    if expected.is_scored:
        print(f"Expected lines: {expected.min_removable_lines}-{expected.max_removable_lines}")
    elif expected.has_paper_value:
        print(
            f"Paper reference: {expected.paper_lines} lines "
            "(no acceptance range for this later source revision)"
        )
    else:
        print("Paper reference: none published; result will be observational")

    # A failed rerun must never leave a previous checkpoint available for the
    # validator. Each invocation starts with an empty per-demo directory.
    demo_output = Path(output_dir) / demo_name
    if demo_output.exists():
        shutil.rmtree(demo_output)
    demo_output.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    # Run container
    container_result = run_docker_container(
        image_name=config["image_name"],
        volumes={
            str(demo_output.absolute()): "/prat/output"
        },
        environment={"PRAT_RUN_ID": run_id},
        remove=True,
        timeout=3600  # 60 min — OpenDDS builds ACE+TAO+OpenDDS twice (security on/off)
    )

    log_file = demo_output / "container.log"
    log_file.write_text(
        container_result.stdout
        + ("\n--- STDERR ---\n" + container_result.stderr if container_result.stderr else ""),
        encoding="utf-8",
    )

    if not container_result.success:
        result = DemoResult(
            demo_name=demo_name,
            success=False,
            removable_lines=None,
            files_analyzed=None,
            key_files_found=[],
            key_files_missing=[],
            within_expected_range=False,
            execution_time=None,
            error_message=f"{container_result.error_message}; see {log_file}"
        )
        _write_demo_manifest(
            demo_output, config, expected, result, log_file, run_id, started_at
        )
        return result

    # Parse results from checkpoint file
    checkpoint_file = demo_output / "workflow_checkpoint.json"

    if not checkpoint_file.exists():
        result = DemoResult(
            demo_name=demo_name,
            success=False,
            removable_lines=None,
            files_analyzed=None,
            key_files_found=[],
            key_files_missing=[],
            within_expected_range=False,
            execution_time=None,
            error_message="Checkpoint file not found"
        )
        _write_demo_manifest(
            demo_output, config, expected, result, log_file, run_id, started_at
        )
        return result

    try:
        with open(checkpoint_file) as f:
            checkpoint = json.load(f)

        # Extract results. `file_line_counts` is keyed by the source path gcov
        # recorded, and `feature_only_source_paths` lists the files that exist
        # only in the feature-enabled build; both are partitions of D_f.
        extraction = checkpoint.get('extraction_result', {})
        removable_lines = extraction.get('total_removable_lines', 0)
        file_line_counts = extraction.get('file_line_counts', {})
        feature_only_files = extraction.get('feature_only_source_paths', [])
        files_analyzed = len(file_line_counts)
        execution_time = checkpoint.get('total_time', 0)

        # Check for key files
        key_files_found = []
        key_files_missing = []

        for key_file in expected.key_files:
            # Check if any analyzed file contains the key file name
            found = any(key_file in analyzed_file for analyzed_file in file_line_counts)
            found = found or any(key_file in feature_file for feature_file in feature_only_files)
            if found:
                key_files_found.append(key_file)
            else:
                key_files_missing.append(key_file)

        # A numerical gate applies only if metadata explicitly configures one.
        within_range = (
            True
            if not expected.is_scored
            else (
                expected.min_removable_lines <= removable_lines
                <= expected.max_removable_lines
            )
        )

        workflow_success = checkpoint.get('success', False) is True
        evidence_success = (
            workflow_success
            and within_range
            and not key_files_missing
        )
        errors = []
        if not workflow_success:
            errors.append(checkpoint.get("error_message") or "workflow failed")
        if not within_range:
            errors.append("measurement is outside the configured compatibility range")
        if key_files_missing:
            errors.append(
                f"expected source evidence is missing: {', '.join(key_files_missing)}"
            )

        result = DemoResult(
            demo_name=demo_name,
            success=evidence_success,
            removable_lines=removable_lines,
            files_analyzed=files_analyzed,
            key_files_found=key_files_found,
            key_files_missing=key_files_missing,
            within_expected_range=within_range,
            execution_time=execution_time,
            error_message="; ".join(errors) or None,
            workflow_success=workflow_success,
        )

        _write_demo_manifest(
            demo_output=demo_output,
            config=config,
            expected=expected,
            result=result,
            container_log=log_file,
            run_id=run_id,
            started_at=started_at,
        )

        # Print summary
        print(f"\n{'='*70}")
        print(f"Demo Results: {demo_name}")
        print(f"{'='*70}")
        print(f"Success: {result.success}")
        print(f"Removable lines: {removable_lines}")
        if expected.is_scored:
            print(f"Expected range: {expected.min_removable_lines}-{expected.max_removable_lines}")
            print(f"Within range: {within_range}")
        elif expected.has_paper_value:
            print(
                f"Paper reference: {expected.paper_lines} "
                "(historical context, not a numerical gate)"
            )
        else:
            print("Paper reference: none published")
        print(f"Files analyzed: {files_analyzed}")
        print(f"Key files found: {', '.join(key_files_found) if key_files_found else 'None'}")
        if key_files_missing:
            print(f"Key files missing: {', '.join(key_files_missing)}")
        print(f"Execution time: {execution_time:.2f}s")
        print(f"Artifacts: {demo_output}")

        return result

    except Exception as e:
        result = DemoResult(
            demo_name=demo_name,
            success=False,
            removable_lines=None,
            files_analyzed=None,
            key_files_found=[],
            key_files_missing=[],
            within_expected_range=False,
            execution_time=None,
            error_message=f"Failed to parse results: {e}"
        )
        _write_demo_manifest(
            demo_output, config, expected, result, log_file, run_id, started_at
        )
        return result


def _write_demo_manifest(
    demo_output: Path,
    config: dict[str, str],
    expected: ExpectedResult,
    result: DemoResult,
    container_log: Path,
    run_id: str,
    started_at: str,
) -> None:
    """Write a small manifest for committee/demo review."""
    artifacts = {
        path.name: str(path)
        for path in sorted(demo_output.iterdir())
        if path.is_file() or path.is_dir()
    }
    artifacts["container.log"] = str(container_log)
    repo_root = Path(__file__).resolve().parent.parent
    source_status = _command_output(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
    )
    artifact_hashes = {
        str(path.relative_to(demo_output)): _sha256_file(path)
        for path in sorted(demo_output.rglob("*"))
        if path.is_file() and path.name != "demo_manifest.json"
    }

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "run_id": run_id,
        "demo": result.demo_name,
        "image": config["image_name"],
        "project": config["project"],
        "feature": config["feature"],
        "expected": asdict(expected),
        "result": asdict(result),
        "artifacts": artifacts,
        "artifact_sha256": artifact_hashes,
        "provenance": {
            "prat_git_commit": _command_output(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
            ),
            "prat_git_dirty": bool(source_status),
            "prat_source_sha256": _tree_digest(repo_root / "src"),
            "dockerfile_sha256": _sha256_file(
                repo_root / config["dockerfile"]
            ),
            "expected_results_sha256": _sha256_file(_PAPER_EXPECTED_PATH),
            "image_id": _command_output(
                [
                    "docker", "image", "inspect", config["image_name"],
                    "--format", "{{.Id}}",
                ]
            ),
        },
    }

    path = demo_output / "demo_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _command_output(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        item for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and not item.name.endswith((".pyc", ".pyo"))
        and not any(part.endswith(".egg-info") for part in item.parts)
    ):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def generate_comparison_report(results: list[DemoResult], output_file: str):
    """
    Generate comparison report showing actual vs expected results.

    Args:
        results: List of demo results
        output_file: Path to output report file
    """
    report_lines = []

    report_lines.append("=" * 80)
    report_lines.append("PRAT Demo Comparison Report")
    report_lines.append("=" * 80)
    report_lines.append("")

    for result in results:
        expected = EXPECTED_RESULTS.get(result.demo_name)

        report_lines.append(f"Demo: {result.demo_name}")
        report_lines.append("-" * 80)

        if expected:
            report_lines.append(f"Description: {expected.description}")

        status = (
            "FAIL"
            if not result.success
            else "OBSERVED"
            if expected and not expected.has_paper_value
            else "COMPATIBLE"
        )
        report_lines.append(f"Status: {status}")

        if result.removable_lines is not None:
            report_lines.append(f"Removable Lines: {result.removable_lines}")
            if expected:
                if expected.is_scored:
                    report_lines.append(
                        f"Expected Range: {expected.min_removable_lines}-"
                        f"{expected.max_removable_lines}"
                    )
                    report_lines.append(
                        f"Within Range: {'YES' if result.within_expected_range else 'NO'}"
                    )
                else:
                    if expected.has_paper_value:
                        report_lines.append(
                            f"Paper Reference: {expected.paper_lines} "
                            "(no modern-version acceptance range)"
                        )
                    else:
                        report_lines.append("Paper Reference: none published")

        if result.files_analyzed is not None:
            report_lines.append(f"Files Analyzed: {result.files_analyzed}")

        if result.key_files_found:
            report_lines.append(f"Key Files Found: {', '.join(result.key_files_found)}")

        if result.key_files_missing:
            report_lines.append(f"Key Files Missing: {', '.join(result.key_files_missing)}")

        if result.execution_time is not None:
            report_lines.append(f"Execution Time: {result.execution_time:.2f}s")

        if result.error_message:
            report_lines.append(f"Error: {result.error_message}")

        report_lines.append("")

    # Summary
    total = len(results)
    compatible = sum(
        1 for r in results
        if r.success and EXPECTED_RESULTS[r.demo_name].has_paper_value
    )
    observed = sum(
        1 for r in results
        if r.success and not EXPECTED_RESULTS[r.demo_name].has_paper_value
    )
    failed = total - compatible - observed

    report_lines.append("=" * 80)
    report_lines.append("Summary")
    report_lines.append("=" * 80)
    report_lines.append(f"Total Demos: {total}")
    report_lines.append(f"Compatible: {compatible}")
    report_lines.append(f"Observed: {observed}")
    report_lines.append(f"Failed: {failed}")
    report_lines.append("=" * 80)

    report_text = "\n".join(report_lines)

    # Print to console
    print("\n" + report_text)

    # Write to file
    with open(output_file, 'w') as f:
        f.write(report_text)

    print(f"\n[+] Report saved to: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PRAT Demo Runner - Build and run Docker-based PRAT demos"
    )

    parser.add_argument(
        "--build",
        choices=list(DEMO_CONFIGS.keys()),
        help="Build specific demo"
    )

    parser.add_argument(
        "--build-all",
        action="store_true",
        help="Build all demos"
    )

    parser.add_argument(
        "--run",
        choices=list(DEMO_CONFIGS.keys()),
        help="Run specific demo"
    )

    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run all demos"
    )

    parser.add_argument(
        "--output",
        default="demo_output",
        help="Output directory for demo results (default: demo_output)"
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Build without using Docker cache"
    )

    parser.add_argument(
        "--report",
        default="demo_report.txt",
        help="Output file for comparison report (default: demo_report.txt)"
    )

    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove each demo's Docker image after it runs (frees disk; these "
             "images are large and rebuildable from their Dockerfiles)"
    )

    args = parser.parse_args()

    # Check Docker availability
    if not check_docker_available():
        print("[!] Docker is not available on this system")
        print("[!] Please install Docker: https://docs.docker.com/get-docker/")
        return 1

    # Build demos
    if args.build:
        success = build_demo(args.build, no_cache=args.no_cache)
        return 0 if success else 1

    if args.build_all:
        print("\n" + "=" * 70)
        print("Building All Demos")
        print("=" * 70)

        results = []
        for demo_name in DEMO_CONFIGS:
            success = build_demo(demo_name, no_cache=args.no_cache)
            results.append(success)

        total = len(results)
        passed = sum(results)

        print(f"\n{'='*70}")
        print(f"Build Summary: {passed}/{total} successful")
        print(f"{'='*70}")

        return 0 if all(results) else 1

    # Run demos
    if args.run:
        result = run_demo(args.run, args.output)

        # Generate report for single demo
        generate_comparison_report([result], args.report)

        if args.cleanup:
            remove_docker_image(DEMO_CONFIGS[args.run]["image_name"], force=True)

        return 0 if result.success else 1

    if args.run_all:
        print("\n" + "=" * 70)
        print("Running All Demos")
        print("=" * 70)

        results = []
        for demo_name in DEMO_CONFIGS:
            result = run_demo(demo_name, args.output)
            results.append(result)
            # Remove the image immediately after its run so large images (aom,
            # ffmpeg, opendds) never accumulate and exhaust the Docker disk.
            if args.cleanup:
                remove_docker_image(DEMO_CONFIGS[demo_name]["image_name"], force=True)

        # Generate comparison report
        generate_comparison_report(results, args.report)

        # Return success if all demos passed
        all_passed = all(r.success for r in results)
        return 0 if all_passed else 1

    # No action specified
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
