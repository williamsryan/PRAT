#!/usr/bin/env python3
"""
Enhanced PRAT CLI with improved user experience.

Features:
- Progress indicators for long-running operations
- Better error messages with actionable suggestions
- Verbose mode for debugging
- Dry-run mode to preview operations
"""


from __future__ import annotations

import argparse
import platform
import shutil
import sys
from pathlib import Path

from .adapters import get_adapter
from .batch import run_batch_analysis
from .compilation import detect_build_system
from .discovery import discover_features
from .docker_runner import check_docker_available
from .environment import verify_dependencies
from .workflow import WorkflowCheckpoint, run_complete_workflow


def _tool_path(tool: str) -> str:
    return shutil.which(tool) or "missing"


class ProgressIndicator:
    """Simple progress indicator for CLI."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.current_step = 0
        self.total_steps = 7

    def step(self, message: str) -> None:
        """Print progress step."""
        self.current_step += 1
        prefix = f"[{self.current_step}/{self.total_steps}]"
        print(f"\n{prefix} {message}")

    def info(self, message: str) -> None:
        """Print info message."""
        if self.verbose:
            print(f"    ℹ {message}")

    def success(self, message: str) -> None:
        """Print success message."""
        print(f"    ✓ {message}")

    def error(self, message: str) -> None:
        """Print error message."""
        print(f"    ✗ {message}")

    def warning(self, message: str) -> None:
        """Print warning message."""
        print(f"    ⚠ {message}")


def list_features(project_path: str, verbose: bool = False) -> int:
    """
    List available features for a project.

    Returns:
        Exit code (0 for success)
    """
    progress = ProgressIndicator(verbose)

    print(f"\n{'='*70}")
    print(f"Discovering Features: {project_path}")
    print(f"{'='*70}")

    # Detect build system
    try:
        build_system = detect_build_system(project_path)
        progress.info(f"Detected build system: {build_system.value}")
    except Exception as e:
        progress.error(f"Failed to detect build system: {e}")
        print("\n💡 Suggestion: Ensure the project directory contains build files")
        print("   (Makefile, CMakeLists.txt, configure, or Cargo.toml)")
        return 1

    # Discovery runs every analyzer that applies, since a project can expose
    # different features through different build systems.
    try:
        from .adapters import get_adapter

        adapter = get_adapter(project_path)
        features = discover_features(project_path, adapter=adapter)

        if not features:
            progress.warning("No features found")
            print("\n💡 Suggestion: This project may not have configurable features")
            print("   or the build system is not fully supported")
            return 0

        print(f"\n✓ Found {len(features)} candidate feature(s):\n")
        for i, feature in enumerate(features, 1):
            desc = f" — {feature.description}" if feature.description else ""
            default = ""
            if feature.default_enabled is not None:
                default = f" [default: {'on' if feature.default_enabled else 'off'}]"
            option = ""
            if feature.raw_name and feature.raw_name != feature.name:
                option = f" (option: {feature.raw_name})"
            source = f" [{feature.source}]" if verbose and feature.source else ""
            print(f"  {i}. {feature.name}{option}{default}{source}{desc}")

        if verbose:
            unfiltered = discover_features(
                project_path, adapter=adapter, apply_filters=False
            )
            discarded = len(unfiltered) - len(features)
            if discarded > 0:
                print(f"\n  {discarded} build option(s) filtered as spurious or "
                      f"developer-specific")

        print("\n💡 To analyze a feature, run:")
        print(f"   prat {project_path} {features[0].name}")
        print("   To analyze every feature (Algorithm 1):")
        print(f"   prat {project_path} --batch")

        return 0

    except Exception as e:
        progress.error(f"Feature discovery failed: {e}")
        print("\n💡 Suggestion: Check that the project has a valid build configuration")
        return 1


def dry_run_analysis(
    project_path: str,
    feature: str,
    run_tests: bool,
    verbose: bool
) -> int:
    """
    Preview what the analysis will do without executing.

    Returns:
        Exit code (0 for success)
    """
    progress = ProgressIndicator(verbose)

    print(f"\n{'='*70}")
    print(f"Dry Run: {project_path} - Feature: {feature}")
    print(f"{'='*70}")

    # Detect build system
    try:
        build_system = detect_build_system(project_path)
        print(f"\n✓ Build system: {build_system.value}")
    except Exception as e:
        progress.error(f"Cannot detect build system: {e}")
        return 1

    # Show what will be executed
    print("\nWorkflow steps:")
    print("  1. Verify dependencies (gcc, make, gcov, etc.)")
    print(f"  2. Compile with {feature} ENABLED")
    print("  3. Generate coverage files (enabled)")
    print(f"  4. Compile with {feature} DISABLED")
    print("  5. Generate coverage files (disabled)")
    print("  6. Diff coverage files")
    print("  7. Extract feature-specific code")

    if run_tests:
        print("\n✓ Test suite will be executed for better coverage")

    print("\nOutput directories:")
    print(f"  - coverage_files_WITH_{feature}_yes/")
    print(f"  - coverage_files_WITH_{feature}_no/")
    print(f"  - diff_{feature}/")
    print("  - HTML report and DOT graph")

    print("\n💡 To execute, remove --dry-run flag")

    return 0


def run_doctor(project_path: str | None = None) -> int:
    """
    Print local environment readiness for PRAT demos and standalone use.

    Returns:
        Exit code (0 if required dependencies are present)
    """
    print("\n" + "=" * 70)
    print("PRAT Doctor")
    print("=" * 70)
    print(f"Python:   {platform.python_version()}")
    print(f"Platform: {platform.platform()}")

    adapter = None
    if project_path and Path(project_path).exists():
        adapter = get_adapter(project_path)
    deps = verify_dependencies(
        build_system=adapter.build_system if adapter else None,
        coverage_tool=adapter.coverage_tool if adapter else None,
    )

    print("\nRequired/coverage tools:")
    for tool in [
        "gcc", "make", "cmake", "cargo", "cargo-llvm-cov", "python3",
        "perl", "gcov", "llvm-cov",
    ]:
        print(f"  {tool:12s} {_tool_path(tool)}")

    print("\nOptional tools:")
    for tool in ["clang", "cmake", "pygmentize", "xdot", "docker"]:
        if tool == "docker":
            status = "available" if check_docker_available() else "missing"
        else:
            status = _tool_path(tool)
        print(f"  {tool:12s} {status}")

    if project_path:
        project = Path(project_path)
        print("\nProject:")
        print(f"  path         {project}")
        print(f"  exists       {project.exists()}")
        if project.exists():
            try:
                build_system = detect_build_system(str(project))
                print(f"  build system {build_system.value}")
            except Exception as exc:
                print(f"  build system error: {exc}")

            print(f"  adapter      {type(adapter).__name__ if adapter else 'none'}")
            if adapter:
                print(f"  coverage     {adapter.coverage_tool}")
                print(f"  source dirs  {', '.join(adapter.source_directories)}")

    print("\nResult:")
    if deps.success:
        print("  required dependencies are available")
        return 0

    print(f"  missing required dependencies: {', '.join(deps.missing_tools)}")
    return 1


def run_analysis(
    project_path: str,
    feature: str,
    run_tests: bool = False,
    extract: bool = False,
    verbose: bool = False,
    output_dir: str | None = None,
    symbolic: bool = False,
    remove: bool = False,
    verify: bool = False,
    all_features_baseline: bool = True,
    skip_features: list[str] | None = None,
) -> int:
    """
    Run PRAT analysis workflow.

    Returns:
        Exit code (0 for success)
    """
    progress = ProgressIndicator(verbose)

    print(f"\n{'='*70}")
    print(f"PRAT Analysis: {project_path} - Feature: {feature}")
    print(f"{'='*70}")

    adapter = get_adapter(project_path)

    # Verify dependencies for the selected adapter.
    progress.step("Verifying dependencies...")
    deps = verify_dependencies(
        build_system=adapter.build_system if adapter else None,
        coverage_tool=adapter.coverage_tool if adapter else None,
    )
    missing = deps.missing_tools

    if missing:
        progress.error(f"Missing dependencies: {', '.join(missing)}")
        print("\n💡 Suggestion: Install missing dependencies:")
        print(f"   sudo apt-get install {' '.join(missing)}")
        return 1

    progress.success("All dependencies available")

    # Run workflow
    try:
        result = run_complete_workflow(
            project_path=project_path,
            feature=feature,
            run_tests=run_tests,
            output_dir=output_dir,
            symbolic=symbolic,
            adapter=adapter,
            remove=remove,
            verify=verify,
            all_features_baseline=all_features_baseline,
            skip_features=skip_features,
        )

        if not result.success:
            progress.error(f"Workflow failed at {result.checkpoint.value}")
            print(f"\n💡 Error: {result.error_message}")

            if result.checkpoint == WorkflowCheckpoint.COMPILE_ENABLED:
                print("\n💡 Suggestion: Check that the project compiles normally:")
                print(f"   cd {project_path} && make clean && make")
            elif result.checkpoint in (
                WorkflowCheckpoint.COVERAGE_ENABLED,
                WorkflowCheckpoint.COVERAGE_DISABLED,
            ):
                print("\n💡 Suggestion: Coverage needs the binary to actually run.")
                print(f"   find {project_path} -name '*.gcda'")
                print("   An empty result means the test suite did not execute.")
            elif result.checkpoint == WorkflowCheckpoint.MAP:
                print("\n💡 Suggestion: Check both coverage directories are populated:")
                print(f"   ls {output_dir or project_path}/coverage_files_*")
            elif result.checkpoint == WorkflowCheckpoint.REMOVE:
                removal = result.removal_result
                if removal and removal.restored:
                    print("\n💡 The source tree was restored from backup.")
                print("\n💡 A failed rebuild means the removed feature set is "
                      "incomplete — a dependent feature likely needs removing too.")
            elif result.checkpoint == WorkflowCheckpoint.VERIFY:
                print("\n💡 Suggestion: Inspect the failing suite output above; "
                      "the comparison reports show exactly which lines were removed.")

            print(f"\n💡 Checkpoint saved to: {output_dir or project_path}/"
                  f"workflow_checkpoint.json")
            return 1

        extraction = result.extraction_result
        if extraction is None:
            progress.error("Workflow succeeded but extraction result is missing")
            return 1

        print(f"\n{'='*70}")
        print("✓ Analysis Complete")
        print(f"{'='*70}")
        print(f"Feature lines (|D_f|): {extraction.total_removable_lines}")
        print(f"Files analyzed: {len(extraction.file_line_counts)}")
        if extraction.excluded_never_executed:
            print(f"Retained (never executed in either build): "
                  f"{extraction.excluded_never_executed}")
        if result.coverage_percent_enabled is not None:
            print(f"Line coverage under T: {result.coverage_percent_enabled:.1f}%")
        print(f"Execution time: {result.total_time:.2f}s")

        if extraction.html_report_path:
            print(f"\n📄 HTML report: {extraction.html_report_path}")
        if extraction.dot_graph_path:
            print(f"📊 DOT graph: {extraction.dot_graph_path}")
        if result.comparison_result and result.comparison_result.index_path:
            print(f"🔍 Comparison reports: {result.comparison_result.index_path}")

        if extraction.file_line_counts:
            sorted_files = sorted(
                extraction.file_line_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            print("\nTop files with feature code:")
            for filename, lines in sorted_files[:5]:
                print(f"  {filename}: {lines} lines")

        if result.removal_result:
            removal = result.removal_result
            print(f"\n✓ Removed {removal.lines_removed} line(s) from "
                  f"{removal.files_modified} file(s)")
            if removal.files_stubbed:
                print(f"  {removal.files_stubbed} dedicated feature file(s) stubbed")
            if removal.skipped_unbalanced:
                print(f"  Balance guard declined {removal.skipped_line_count} line(s) "
                      f"that could not be removed without unbalancing delimiters")
            if removal.backup_dir:
                print(f"  Backup: {removal.backup_dir}")

        if result.verification_result:
            ver = result.verification_result
            print(f"\n✓ Verification: {ver.status.value} "
                  f"({ver.total_tests_passed}/{ver.total_tests_run} tests passed)")

        if not remove:
            print("\n💡 Next steps:")
            print("   - Review the HTML report and comparison reports")
            print("   - Run with --remove to strip the feature's code and rebuild")
            print("   - Run with --batch to analyze every feature (Algorithm 1)")

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠ Analysis interrupted by user")
        return 130
    except Exception as e:
        progress.error(f"Unexpected error: {e}")

        if verbose:
            import traceback
            print("\nFull traceback:")
            traceback.print_exc()

        print("\n💡 Suggestion: Run with --verbose for detailed error information")
        return 1


def run_variant_chain(
    project_path: str,
    variant_count: int,
    output_dir: str | None = None,
    run_tests: bool = False,
    fuzz: bool = False,
    fuzz_seconds: int = 600,
    verbose: bool = False,
) -> int:
    """Build the paper's cumulative variant chain, optionally fuzzing each variant.

    Returns:
        Exit code: 0 when every variant built and no crash was introduced.
    """
    from .fuzzing import (
        FuzzCampaign,
        check_boofuzz_available,
        compare_to_baseline,
        fuzz_variant,
    )
    from .variants import build_variant_chain

    progress = ProgressIndicator(verbose)
    adapter = get_adapter(project_path)

    if fuzz and not check_boofuzz_available():
        progress.error("Fuzzing requested but boofuzz is not installed")
        print("\n💡 Install it with: pip install 'prat[fuzz]'")
        return 1

    chain = build_variant_chain(
        project_path,
        variant_count=variant_count,
        output_dir=output_dir,
        adapter=adapter,
        run_tests=run_tests,
        apply_removal=True,
    )

    if not chain.variants:
        progress.error(chain.error_message or "Variant chain produced nothing")
        return 1

    if not fuzz:
        if not chain.success:
            print(f"\n⚠ Chain stopped early: {chain.error_message or 'see above'}")
            return 1
        print("\n💡 Re-run with --fuzz to measure per-variant coverage and "
              "crashes (the paper's correctness table)")
        return 0

    # --- Fuzz each variant --------------------------------------------------
    print(f"\n{'=' * 70}")
    print(f"Fuzzing {len(chain.variants)} variant(s), "
          f"{fuzz_seconds}s each")
    print(f"{'=' * 70}")

    campaign = FuzzCampaign()
    fuzz_failed = False
    for variant in chain.variants:
        if not variant.success or not variant.binary_path:
            print(f"\n[{variant.label}] skipped — variant did not build")
            fuzz_failed = True
            continue

        print(f"\n[{variant.label}] fuzzing "
              f"({len(variant.removed_features)} feature(s) removed)...")
        result = fuzz_variant(
            broker_binary=variant.binary_path,
            project_path=project_path,
            variant=variant.label,
            removed_features=variant.removed_features,
            duration_seconds=fuzz_seconds,
            coverage_tool=adapter.coverage_tool if adapter else "gcov",
            source_directories=tuple(
                adapter.source_directories if adapter else ("src", "lib")
            ),
            work_dir=str(Path(output_dir or project_path) / f"fuzz_{variant.label}"),
        )
        campaign.results.append(result)

        if result.error_message:
            print(f"    [!] {result.error_message}")
        if not result.success:
            fuzz_failed = True

    compare_to_baseline(campaign)

    print(f"\n{'=' * 70}")
    print("FUZZING RESULTS (paper correctness table)")
    print(f"{'=' * 70}")
    print(campaign.table())
    print()

    if campaign.baseline_crashes:
        print(f"Crashes already present in variant 0 (pre-existing): "
              f"{', '.join(campaign.baseline_crashes)}")

    if fuzz_failed:
        print("\n✗ One or more variants were not fuzzed successfully")
        return 1

    if campaign.any_introduced_crash:
        print("\n✗ Crashes introduced by feature removal:")
        for variant_label, crashes in campaign.introduced_crashes.items():
            print(f"    {variant_label}: {', '.join(crashes)}")
        return 1

    print("\n✓ No crash was introduced by feature removal")
    return 0


def _package_version() -> str:
    try:
        from importlib import metadata
        return metadata.version("prat")
    except Exception:
        return "1.0.0"


# Docker demo names (authoritative list lives in src/demo-runner.py DEMO_CONFIGS).
_REPRODUCE_DEMOS = [
    "mosquitto-tls",
    "mosquitto-bridge",
    "ffmpeg-dca",
    "uamqp-websockets",
    "opendds-content-filtered-topic",
    "quiche-qlog",
    "rav1e-serialize",
    "aom-encoder",
]


def run_reproduce(argv: list[str]) -> int:
    """Build and run source-pinned Docker compatibility demos.

    Thin wrapper over ``src/demo-runner.py`` and
    ``scripts/validate_paper_results.py`` so the published ``prat`` entry point
    offers a one-command compatibility check. The paper did not publish exact
    source revisions, so this command does not claim bit-for-bit reproduction.
    Disk-safe by default: each image is removed after its run.
    """
    import subprocess

    p = argparse.ArgumentParser(
        prog="prat reproduce",
        description="Run source-pinned compatibility demos and compare paper values",
    )
    p.add_argument("demo", nargs="?", choices=_REPRODUCE_DEMOS,
                   help="Demo to reproduce (omit and pass --all for every demo)")
    p.add_argument("--all", action="store_true", help="Reproduce all demos (per-demo, disk-safe)")
    p.add_argument("--output", default="results/docker", help="Output directory (default: results/docker)")
    p.add_argument("--keep-images", action="store_true",
                   help="Do NOT remove Docker images after each run (default: remove)")
    p.add_argument("--no-validate", action="store_true", help="Skip the validation step")
    args = p.parse_args(argv)

    if not args.all and not args.demo:
        p.error("specify a demo name or --all")

    repo_root = Path(__file__).resolve().parents[2]
    runner = repo_root / "src" / "demo-runner.py"
    validator = repo_root / "scripts" / "validate_paper_results.py"
    if not runner.exists():
        print("✗ `prat reproduce` requires a source checkout (editable install).")
        print(f"  Expected runner at: {runner}")
        return 1

    if not check_docker_available():
        print("✗ Docker is not available. Install/start Docker and try again.")
        return 1

    cleanup = [] if args.keep_images else ["--cleanup"]
    demos = _REPRODUCE_DEMOS if args.all else [args.demo]

    for demo in demos:
        print(f"\n{'='*70}\nCompatibility target: {demo}\n{'='*70}")
        build_proc = subprocess.run([sys.executable, str(runner), "--build", demo])
        if build_proc.returncode != 0:
            print(f"✗ Failed to build reproduction demo: {demo}")
            return build_proc.returncode or 1
        run_proc = subprocess.run(
            [sys.executable, str(runner), "--run", demo, *cleanup, "--output", args.output]
        )
        if run_proc.returncode != 0:
            print(f"✗ Failed to run reproduction demo: {demo}")
            return run_proc.returncode or 1

    if not args.no_validate:
        validation_proc = subprocess.run(
            [
                sys.executable,
                str(validator),
                f"{args.output}/",
                "--strict",
                *([] if args.all else ["--target", args.demo]),
                "--json",
                str(Path(args.output) / "validation_report.json"),
            ]
        )
        if validation_proc.returncode != 0:
            print("✗ Reproduction results did not pass strict validation")
            return validation_proc.returncode or 1
    return 0


def main() -> int:
    """Main CLI entry point."""
    # Subcommand: `prat reproduce ...` (handled before the analysis arg parser).
    if len(sys.argv) > 1 and sys.argv[1] == "reproduce":
        return run_reproduce(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.argv[1] = "--doctor"

    parser = argparse.ArgumentParser(
        description="PRAT - Protocol Representation and Analysis Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check local readiness
  prat doctor
  prat doctor App/mosquitto

  # List available features
  prat App/mosquitto --list

  # Analyze a feature
  prat App/mosquitto TLS

  # Analyze with test suite
  prat App/mosquitto TLS --tests

  # Preview analysis without executing
  prat App/mosquitto TLS --dry-run

  # Reproduce a paper Docker demo (disk-safe; removes image after run)
  prat reproduce mosquitto-tls
  prat reproduce --all

  # Remove the feature's code, rebuild, and re-run the tests
  prat App/mosquitto TLS --remove

  # Analyze every discovered feature (Algorithm 1: n+1 builds)
  prat App/mosquitto --batch

  # Include KLEE-generated tests in T (paper Table 3 parameters)
  prat App/mosquitto TLS --symbolic

  # Build the paper's 8-variant chain and fuzz each one over MQTT
  prat App/mosquitto --variants 8 --fuzz

  # Verbose output for debugging
  prat App/mosquitto TLS --verbose

For more information, see docs/API.md
        """
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"PRAT {_package_version()}",
        help="Show PRAT version and exit",
    )

    parser.add_argument(
        "project",
        nargs="?",
        help="Path to project directory"
    )

    parser.add_argument(
        "feature",
        nargs="?",
        help="Feature to analyze (required unless --list, --batch, or doctor is used)"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available features for the project"
    )

    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check local dependencies and optional project adapter detection"
    )

    parser.add_argument(
        "--extract",
        action="store_true",
        help="Generate HTML report and DOT graph (enabled by default)"
    )

    parser.add_argument(
        "--tests",
        action="store_true",
        help="Run test suite during compilation for better coverage"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output for debugging"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview operations without executing"
    )

    parser.add_argument(
        "--output", "-o",
        help="Output directory for results (default: project directory)"
    )

    parser.add_argument(
        "--batch",
        action="store_true",
        help="Analyze ALL discovered features (batch mode)"
    )
    parser.add_argument(
        "--paper-algorithm",
        action="store_true",
        help="Run Algorithm 1 end to end: all-feature baseline, KLEE test "
             "generation, per-feature mapping, union removal, and verification",
    )

    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove identified feature code from source (creates backup)"
    )

    parser.add_argument(
        "--symbolic",
        action="store_true",
        help="Generate experimental KLEE symbolic tests"
    )

    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run post-removal verification (rebuild + test replay)"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip post-removal verification (it runs by default with --remove)"
    )
    parser.add_argument(
        "--variants",
        type=int,
        metavar="N",
        default=None,
        help="Build the paper's cumulative variant chain: N variants, where "
             "variant 0 has all features and variant i removes one more than "
             "variant i-1 (the paper uses 8)"
    )
    parser.add_argument(
        "--fuzz",
        action="store_true",
        help="Fuzz each variant over MQTT with Boofuzz and report line/function "
             "coverage per variant (requires 'pip install prat[fuzz]')"
    )
    parser.add_argument(
        "--fuzz-seconds",
        type=int,
        default=600,
        metavar="S",
        help="Per-variant fuzzing budget in seconds (default: 600)"
    )
    parser.add_argument(
        "--default-baseline",
        action="store_true",
        help="Use the project's default configuration as the baseline instead "
             "of Algorithm 1's all-features B_all (single-feature and --batch). "
             "Exploratory only: the result is labelled project-default and is "
             "not accepted as a paper reproduction"
    )
    parser.add_argument(
        "--skip-feature",
        action="append",
        default=[],
        metavar="NAME",
        help="Leave a discovered build option out of F because this "
             "environment cannot compile it (missing library, platform-only "
             "option). Repeatable. Recorded in the checkpoint as "
             "features_excluded; in --batch mode the option is also not analyzed"
    )

    args = parser.parse_args()

    if args.paper_algorithm:
        args.batch = True
        args.symbolic = True
        args.remove = True
        args.no_verify = False

    if args.doctor:
        return run_doctor(args.project)

    # Validate arguments
    if not args.list and not args.batch and not args.feature:
        parser.error("feature is required unless --list, --batch, or doctor is used")

    if not args.project:
        parser.error("project is required")

    # Check project exists
    project_path = Path(args.project)
    if not project_path.exists():
        print(f"✗ Error: Project directory not found: {args.project}")
        print("\n💡 Suggestion: Check the path and try again")
        return 1

    # List features mode
    if args.list:
        return list_features(str(project_path), args.verbose)

    # Batch mode — Algorithm 1 over every discovered feature
    if args.batch:
        batch_result = run_batch_analysis(
            project_path=str(project_path),
            output_dir=args.output,
            run_tests=args.tests,
            symbolic=args.symbolic,
            all_features_baseline=True if args.paper_algorithm else not args.default_baseline,
            skip_features=args.skip_feature or None,
            remove=args.remove,
            verify=not args.no_verify,
        )
        if batch_result.success:
            print(f"\n✓ Batch analysis complete: "
                  f"{batch_result.features_analyzed} feature(s) analyzed, "
                  f"{batch_result.builds_performed} build(s)")
            if batch_result.feature_graph_path:
                print(f"📈 Feature graph: {batch_result.feature_graph_path}")
            return 0
        if batch_result.error_message:
            print(f"\n✗ Batch analysis failed: {batch_result.error_message}")
        return 1

    # Variant chain mode — the paper's correctness evaluation
    if args.variants:
        return run_variant_chain(
            str(project_path),
            variant_count=args.variants,
            output_dir=args.output,
            run_tests=args.tests,
            fuzz=args.fuzz,
            fuzz_seconds=args.fuzz_seconds,
            verbose=args.verbose,
        )

    # Dry run mode
    if args.dry_run:
        return dry_run_analysis(
            str(project_path),
            args.feature,
            args.tests,
            args.verbose
        )

    # Run analysis
    return run_analysis(
        project_path=str(project_path),
        feature=args.feature,
        run_tests=args.tests,
        extract=args.extract,
        verbose=args.verbose,
        output_dir=args.output,
        symbolic=getattr(args, "symbolic", False),
        remove=getattr(args, "remove", False),
        # Verification is part of the paper's removal step, so it runs by
        # default once anything has been removed; --no-verify opts out.
        verify=not getattr(args, "no_verify", False),
        all_features_baseline=not args.default_baseline,
        skip_features=args.skip_feature or None,
    )


if __name__ == "__main__":
    sys.exit(main())
