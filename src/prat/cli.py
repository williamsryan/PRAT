#!/usr/bin/env python3
"""
Enhanced PRAT CLI with improved user experience.

Features:
- Progress indicators for long-running operations
- Better error messages with actionable suggestions
- Verbose mode for debugging
- Dry-run mode to preview operations
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from .batch import run_batch_analysis
from .compilation import BuildSystem, detect_build_system
from .discovery import (
    discover_features_autotools,
    discover_features_cargo,
    discover_features_cmake,
    discover_features_make,
)
from .environment import verify_dependencies
from .removal import remove_feature_code
from .verification import verify_correctness
from .workflow import WorkflowCheckpoint, run_complete_workflow


class ProgressIndicator:
    """Simple progress indicator for CLI."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.current_step = 0
        self.total_steps = 7

    def step(self, message: str):
        """Print progress step."""
        self.current_step += 1
        prefix = f"[{self.current_step}/{self.total_steps}]"
        print(f"\n{prefix} {message}")

    def info(self, message: str):
        """Print info message."""
        if self.verbose:
            print(f"    ℹ {message}")

    def success(self, message: str):
        """Print success message."""
        print(f"    ✓ {message}")

    def error(self, message: str):
        """Print error message."""
        print(f"    ✗ {message}")

    def warning(self, message: str):
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

    # Discover features based on build system
    try:
        if build_system == BuildSystem.MAKE:
            features = discover_features_make(project_path)
        elif build_system == BuildSystem.CMAKE:
            features = discover_features_cmake(project_path)
        elif build_system == BuildSystem.AUTOTOOLS:
            features = discover_features_autotools(project_path)
        elif build_system == BuildSystem.CARGO:
            features = discover_features_cargo(project_path)
        else:
            progress.error(f"Unsupported build system: {build_system.value}")
            return 1

        if not features:
            progress.warning("No features found")
            print("\n💡 Suggestion: This project may not have configurable features")
            print("   or the build system is not fully supported")
            return 0

        print(f"\n✓ Found {len(features)} features:\n")
        for i, feature in enumerate(features, 1):
            desc = f" — {feature.description}" if feature.description else ""
            default = ""
            if feature.default_enabled is not None:
                default = f" [default: {'on' if feature.default_enabled else 'off'}]"
            print(f"  {i}. {feature.name}{desc}{default}")

        print("\n💡 To analyze a feature, run:")
        print(f"   prat {project_path} {features[0].name}")

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


def run_analysis(
    project_path: str,
    feature: str,
    run_tests: bool = False,
    extract: bool = False,
    verbose: bool = False,
    output_dir: Optional[str] = None,
    symbolic: bool = False,
    remove: bool = False,
    verify: bool = False,
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

    # Verify dependencies first
    progress.step("Verifying dependencies...")
    deps = verify_dependencies()
    missing = deps.missing_tools

    if missing:
        progress.error(f"Missing dependencies: {', '.join(missing)}")
        print("\n💡 Suggestion: Install missing dependencies:")
        print(f"   sudo apt-get install {' '.join(missing)}")
        return 1

    progress.success("All dependencies available")

    # Run workflow
    try:
        from .adapters import get_adapter
        adapter = get_adapter(project_path)

        result = run_complete_workflow(
            project_path=project_path,
            feature=feature,
            run_tests=run_tests,
            output_dir=output_dir,
            symbolic=symbolic,
            adapter=adapter,
        )

        if not result.success:
            progress.error(f"Workflow failed at {result.checkpoint.value}")
            print(f"\n💡 Error: {result.error_message}")

            # Provide specific suggestions based on checkpoint
            if result.checkpoint == WorkflowCheckpoint.COMPILE_ENABLED:
                print("\n💡 Suggestion: Check that the project compiles normally:")
                print(f"   cd {project_path} && make clean && make")
            elif result.checkpoint == WorkflowCheckpoint.COVERAGE_ENABLED:
                print("\n💡 Suggestion: Ensure coverage files were generated:")
                print(f"   find {project_path} -name '*.gcda'")
            elif result.checkpoint == WorkflowCheckpoint.DIFF:
                print("\n💡 Suggestion: Check coverage directories exist:")
                print(f"   ls coverage_files_WITH_{feature}_yes/")
                print(f"   ls coverage_files_WITH_{feature}_no/")

            print(f"\n💡 Checkpoint saved to: {project_path}/workflow_checkpoint.json")
            print("   You can inspect this file for detailed error information")

            return 1

        # Success!
        extraction = result.extraction_result
        if extraction is None:
            progress.error("Workflow succeeded but extraction result is missing")
            return 1

        print(f"\n{'='*70}")
        print("✓ Analysis Complete")
        print(f"{'='*70}")
        print(f"Removable lines: {extraction.total_removable_lines}")
        print(f"Files analyzed: {len(extraction.file_line_counts)}")
        print(f"Execution time: {result.total_time:.2f}s")

        if extraction.html_report_path:
            print(f"\n📄 HTML report: {extraction.html_report_path}")

        if extraction.dot_graph_path:
            print(f"📊 DOT graph: {extraction.dot_graph_path}")

        # Show top files
        if extraction.file_line_counts:
            sorted_files = sorted(
                extraction.file_line_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )

            print("\nTop files with removable code:")
            for filename, lines in sorted_files[:5]:
                print(f"  {filename}: {lines} lines")

        # Optional: Remove feature code
        if remove and result.extraction_result:
            print(f"\n{'='*70}")
            print(f"Feature Removal: {feature}")
            print(f"{'='*70}")
            diff_r = result.diff_result
            removal_result = remove_feature_code(
                result.extraction_result,
                project_path,
                feature,
                feature_only_files=diff_r.feature_only_files if diff_r else None,
                rebuild=True,
            )
            if removal_result.success:
                print(f"✓ Removed {removal_result.lines_removed} lines")
            else:
                print(f"✗ Removal failed: {removal_result.error_message}")

        # Optional: Post-removal verification
        if verify:
            ver_result = verify_correctness(project_path, adapter=adapter)
            if not ver_result.success:
                print(f"⚠ Verification: {ver_result.total_tests_failed} test(s) failed")
                return 1

        if not remove:
            print("\n💡 Next steps:")
            print("   - Review HTML report for detailed analysis")
            print("   - Run with --remove to strip feature code")
            print("   - Run with --verify to test after removal")

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


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="PRAT - Protocol Representation and Analysis Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available features
  prat App/mosquitto --list

  # Analyze a feature
  prat App/mosquitto TLS

  # Analyze with test suite
  prat App/mosquitto TLS --tests

  # Preview analysis without executing
  prat App/mosquitto TLS --dry-run

  # Verbose output for debugging
  prat App/mosquitto TLS --verbose

For more information, see docs/API.md
        """
    )

    parser.add_argument(
        "project",
        help="Path to project directory"
    )

    parser.add_argument(
        "feature",
        nargs="?",
        help="Feature to analyze (required unless --list is used)"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available features for the project"
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

    args = parser.parse_args()

    # Validate arguments
    if not args.list and not args.batch and not args.feature:
        parser.error("feature is required unless --list is used")

    # Check project exists
    project_path = Path(args.project)
    if not project_path.exists():
        print(f"✗ Error: Project directory not found: {args.project}")
        print("\n💡 Suggestion: Check the path and try again")
        return 1

    # List features mode
    if args.list:
        return list_features(str(project_path), args.verbose)

    # Batch mode
    if args.batch:
        batch_result = run_batch_analysis(
            project_path=str(project_path),
            output_dir=args.output,
            run_tests=args.tests,
        )
        if batch_result.success:
            print(f"\n✓ Batch analysis complete: {batch_result.features_analyzed} features analyzed")
            if batch_result.feature_graph_path:
                print(f"📈 Feature graph: {batch_result.feature_graph_path}")
            return 0
        return 1

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
        symbolic=getattr(args, 'symbolic', False),
        remove=getattr(args, 'remove', False),
        verify=getattr(args, 'verify', False),
    )


if __name__ == "__main__":
    sys.exit(main())
