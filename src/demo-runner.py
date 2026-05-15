#!/usr/bin/env python3
"""
PRAT Demo Runner

This script orchestrates building and running Docker-based PRAT demos,
validates results against expected values, and generates comparison reports.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add prat module to path
sys.path.insert(0, str(Path(__file__).parent))

from prat.docker_runner import build_docker_image, check_docker_available, run_docker_container


@dataclass
class ExpectedResult:
    """Expected results for a demo."""
    min_removable_lines: int
    max_removable_lines: int
    key_files: list[str]
    description: str


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


# Expected results for each demo
EXPECTED_RESULTS = {
    "mosquitto-tls": ExpectedResult(
        min_removable_lines=500,
        max_removable_lines=1500,
        key_files=["net.c", "tls_mosq.c"],
        description="Mosquitto TLS feature analysis"
    ),
    "mosquitto-bridge": ExpectedResult(
        min_removable_lines=300,
        max_removable_lines=800,
        key_files=["bridge.c"],
        description="Mosquitto Bridge feature analysis"
    ),
    "ffmpeg-x264": ExpectedResult(
        min_removable_lines=1000,
        max_removable_lines=5000,
        key_files=["libavcodec/libx264.c"],
        description="FFmpeg x264 encoder feature analysis"
    )
}


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
    "ffmpeg-x264": {
        "dockerfile": "docker/demo3/Dockerfile",
        "image_name": "prat-demo:ffmpeg",
        "feature": "x264",
        "project": "ffmpeg"
    }
}


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
    print(f"Expected lines: {expected.min_removable_lines}-{expected.max_removable_lines}")

    # Create output directory
    demo_output = Path(output_dir) / demo_name
    demo_output.mkdir(parents=True, exist_ok=True)

    # Run container
    container_result = run_docker_container(
        image_name=config["image_name"],
        volumes={
            str(demo_output.absolute()): "/prat/output"
        },
        remove=True,
        timeout=1800  # 30 minute timeout
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
        _write_demo_manifest(demo_output, config, expected, result, log_file)
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
        _write_demo_manifest(demo_output, config, expected, result, log_file)
        return result

    try:
        with open(checkpoint_file) as f:
            checkpoint = json.load(f)

        # Extract results
        extraction = checkpoint.get('extraction_result', {})
        removable_lines = extraction.get('total_removable_lines', 0)
        file_line_counts = extraction.get('file_line_counts', {})
        files_analyzed = len(file_line_counts)
        execution_time = checkpoint.get('total_time', 0)

        # Check for key files
        key_files_found = []
        key_files_missing = []

        for key_file in expected.key_files:
            # Check if any analyzed file contains the key file name
            found = any(key_file in analyzed_file for analyzed_file in file_line_counts)
            if found:
                key_files_found.append(key_file)
            else:
                key_files_missing.append(key_file)

        # Check if within expected range
        within_range = (
            expected.min_removable_lines <= removable_lines <= expected.max_removable_lines
        )

        result = DemoResult(
            demo_name=demo_name,
            success=checkpoint.get('success', False),
            removable_lines=removable_lines,
            files_analyzed=files_analyzed,
            key_files_found=key_files_found,
            key_files_missing=key_files_missing,
            within_expected_range=within_range,
            execution_time=execution_time
        )

        _write_demo_manifest(
            demo_output=demo_output,
            config=config,
            expected=expected,
            result=result,
            container_log=log_file,
        )

        # Print summary
        print(f"\n{'='*70}")
        print(f"Demo Results: {demo_name}")
        print(f"{'='*70}")
        print(f"Success: {result.success}")
        print(f"Removable lines: {removable_lines}")
        print(f"Expected range: {expected.min_removable_lines}-{expected.max_removable_lines}")
        print(f"Within range: {within_range}")
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
        _write_demo_manifest(demo_output, config, expected, result, log_file)
        return result


def _write_demo_manifest(
    demo_output: Path,
    config: dict[str, str],
    expected: ExpectedResult,
    result: DemoResult,
    container_log: Path,
) -> None:
    """Write a small manifest for committee/demo review."""
    artifacts = {
        path.name: str(path)
        for path in sorted(demo_output.iterdir())
        if path.is_file() or path.is_dir()
    }
    artifacts["container.log"] = str(container_log)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "demo": result.demo_name,
        "image": config["image_name"],
        "project": config["project"],
        "feature": config["feature"],
        "expected": asdict(expected),
        "result": asdict(result),
        "artifacts": artifacts,
    }

    path = demo_output / "demo_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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

        report_lines.append(f"Status: {'PASS' if result.success else 'FAIL'}")

        if result.removable_lines is not None:
            report_lines.append(f"Removable Lines: {result.removable_lines}")
            if expected:
                report_lines.append(
                    f"Expected Range: {expected.min_removable_lines}-{expected.max_removable_lines}"
                )
                report_lines.append(
                    f"Within Range: {'YES' if result.within_expected_range else 'NO'}"
                )

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
    passed = sum(1 for r in results if r.success and r.within_expected_range)

    report_lines.append("=" * 80)
    report_lines.append("Summary")
    report_lines.append("=" * 80)
    report_lines.append(f"Total Demos: {total}")
    report_lines.append(f"Passed: {passed}")
    report_lines.append(f"Failed: {total - passed}")
    report_lines.append(f"Success Rate: {(passed/total*100):.1f}%")
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

        return 0 if result.success and result.within_expected_range else 1

    if args.run_all:
        print("\n" + "=" * 70)
        print("Running All Demos")
        print("=" * 70)

        results = []
        for demo_name in DEMO_CONFIGS:
            result = run_demo(demo_name, args.output)
            results.append(result)

        # Generate comparison report
        generate_comparison_report(results, args.report)

        # Return success if all demos passed
        all_passed = all(
            r.success and r.within_expected_range for r in results
        )
        return 0 if all_passed else 1

    # No action specified
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
