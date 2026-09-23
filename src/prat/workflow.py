"""
Workflow orchestration module for PRAT.

Runs the paper's five-step pipeline for a single feature:

1. Feature identification (see :mod:`prat.discovery`; the feature is given here)
2. Feature-to-code mapping — build with and without the feature, collect
   coverage under the test suite T = U u S, compute D_f = L_all \\ L_f
3. Feature selection (the analyst's step; reports and the feature graph feed it)
4. Feature removal — blank the lines in D_f and rebuild
5. Testing — re-run T against the debloated build and check for crashes

Steps 4 and 5 run only when requested, because the paper places feature
selection by a human between mapping and removal. When they do run, a failed
rebuild or a crashing test fails the workflow rather than being logged and
ignored.

:func:`run_batch_analysis` in :mod:`prat.batch` is the whole-program form of the
same pipeline and is what Algorithm 1 describes; this module is the
single-feature entry point it builds on.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .adapters import ProjectAdapter, get_adapter
from .compilation import BuildSystem, CompilationResult, compile_project, compile_with_adapter
from .coverage import (
    CoverageResult,
    generate_coverage,
    generate_coverage_with_adapter,
    test_plan_digest,
)
from .diff import ComparisonResult, generate_comparison_reports
from .environment import verify_dependencies
from .extraction import ExtractionResult, extract_from_mapping
from .gcov import load_coverage_dir
from .mapping import FeatureMapping, coverage_percent, map_feature_from_coverage
from .mapping import protected_lines as mapping_protected
from .removal import RemovalResult, remove_feature_code, restore_from_backup
from .reporting import (
    generate_dot_graph,
    generate_html_report,
    generate_json_report,
)
from .symbolic import KleeConfig, SymbolicResult, check_klee_available, generate_symbolic_tests
from .verification import (
    VerificationResult,
    capture_reference_outputs,
    verify_correctness,
)


class WorkflowCheckpoint(Enum):
    """Workflow checkpoints for resume functionality."""

    START = "start"
    SYMBOLIC = "symbolic"
    COMPILE_ENABLED = "compile_enabled"
    COVERAGE_ENABLED = "coverage_enabled"
    COMPILE_DISABLED = "compile_disabled"
    COVERAGE_DISABLED = "coverage_disabled"
    MAP = "map"
    EXTRACT = "extract"
    REMOVE = "remove"
    VERIFY = "verify"
    COMPLETE = "complete"


@dataclass
class WorkflowResult:
    """Result of complete workflow execution."""

    success: bool
    project: str
    feature: str
    compilation_enabled: CompilationResult | None
    compilation_disabled: CompilationResult | None
    coverage_enabled: CoverageResult | None
    coverage_disabled: CoverageResult | None
    extraction_result: ExtractionResult | None
    total_time: float
    checkpoint: WorkflowCheckpoint
    error_message: str | None = None
    symbolic_result: SymbolicResult | None = None
    comparison_result: ComparisonResult | None = None
    removal_result: RemovalResult | None = None
    verification_result: VerificationResult | None = None
    coverage_percent_enabled: float | None = None
    coverage_percent_disabled: float | None = None
    run_id: str | None = None

    # The mapping D_f. Excluded from serialization because it carries full
    # source text; ExtractionResult is the serializable projection of it.
    mapping: FeatureMapping | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result["checkpoint"] = self.checkpoint.value
        result.pop("mapping", None)
        return result

    def save_checkpoint(self, output_dir: str) -> bool:
        """Save workflow state to a checkpoint file."""
        checkpoint_file = Path(output_dir) / "workflow_checkpoint.json"
        temporary = checkpoint_file.with_suffix(".json.tmp")
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            with open(temporary, "w") as handle:
                json.dump(self.to_dict(), handle, indent=2, default=str)
            temporary.replace(checkpoint_file)
            print(f"[+] Checkpoint saved to {checkpoint_file}")
            return True
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            print(f"[!] Failed to save checkpoint: {exc}")
            return False


def run_complete_workflow(
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: str | None = None,
    build_system: BuildSystem | None = None,
    adapter: ProjectAdapter | None = None,
    symbolic: bool = False,
    klee_config: KleeConfig | None = None,
    remove: bool = False,
    verify: bool = True,
    baseline_coverage_dir: str | None = None,
    reuse_baseline: bool = False,
) -> WorkflowResult:
    """
    Execute the PRAT pipeline for one feature.

    Args:
        project_path: Path to project root directory.
        feature: Feature name to analyze.
        run_tests: Run the project's test suite during compilation.
        output_dir: Directory for output files (default: project_path).
        build_system: Build system to use (auto-detected if None).
        adapter: ProjectAdapter to use (auto-detected if None). When provided,
            overrides build_system and uses adapter paths.
        symbolic: Generate the symbolic test set S via KLEE and include it in T.
        klee_config: KLEE configuration; defaults to the paper's parameters.
        remove: Perform step 4 — remove the mapped lines and rebuild.
        verify: Perform step 5 — re-run T against the debloated build. Only
            meaningful together with ``remove``.
        baseline_coverage_dir: Reuse an existing all-features coverage directory
            as L_all instead of rebuilding it. This is how batch analysis
            realizes Algorithm 1's n+1 builds.
        reuse_baseline: Whether ``baseline_coverage_dir`` should be trusted
            without rebuilding the all-features binary.

    Returns:
        WorkflowResult with all outputs and statistics.
    """
    start_time = time.time()

    if output_dir is None:
        output_dir = project_path

    project_name = Path(project_path).name

    print(f"\n{'=' * 70}")
    print(f"PRAT Workflow: {project_name} - Feature: {feature}")
    print(f"{'=' * 70}\n")

    result = WorkflowResult(
        success=False,
        project=project_name,
        feature=feature,
        compilation_enabled=None,
        compilation_disabled=None,
        coverage_enabled=None,
        coverage_disabled=None,
        extraction_result=None,
        total_time=0.0,
        checkpoint=WorkflowCheckpoint.START,
        run_id=os.environ.get("PRAT_RUN_ID") or str(uuid.uuid4()),
    )

    def fail(message: str) -> WorkflowResult:
        print(f"[!] {message}")
        result.error_message = message
        result.total_time = time.time() - start_time
        if not result.save_checkpoint(output_dir):
            result.error_message = f"{message}; checkpoint could not be saved"
        return result

    try:
        if adapter is None:
            adapter = get_adapter(project_path)
        if adapter:
            print(f"[+] Detected project adapter: {type(adapter).__name__}")
            print(f"    Build system: {adapter.build_system.value}")
            print(f"    Coverage tool: {adapter.coverage_tool}")
            print(f"    Source dirs: {', '.join(adapter.source_directories)}\n")
        else:
            return fail(
                "No project adapter can execute and validate this build system; "
                "refusing to produce compile-only coverage"
            )

        if symbolic and adapter.build_system == BuildSystem.CARGO:
            return fail(
                "The KLEE symbolic-test path supports C/C++ LLVM bitcode, not "
                "Cargo/Rust projects"
            )

        # --- Step 0: environment ------------------------------------------
        print("[1/8] Verifying environment dependencies...")
        deps = verify_dependencies(
            build_system=adapter.build_system,
            coverage_tool=adapter.coverage_tool,
        )
        if deps.missing_tools:
            return fail(f"Missing dependencies: {', '.join(deps.missing_tools)}")
        print("[+] All dependencies verified\n")

        # --- Algorithm 1 line 2: S <- SymbolicTestGeneration(P) -----------
        symbolic_tests: list[str] = []
        if symbolic:
            result.checkpoint = WorkflowCheckpoint.SYMBOLIC
            print("[2/8] Generating symbolic test set S (KLEE)...")
            local = check_klee_available(use_docker=False)
            if local or check_klee_available(use_docker=True):
                symbolic_result = generate_symbolic_tests(
                    project_path=project_path,
                    config=klee_config,
                    output_dir=str(Path(output_dir) / "klee_tests"),
                    use_docker=not local,
                    replay=False,  # replayed per build, during coverage
                )
                result.symbolic_result = symbolic_result
                if symbolic_result.success:
                    symbolic_tests = list(symbolic_result.test_cases)
                    print(f"[+] Generated {symbolic_result.test_count} symbolic "
                          f"test case(s); T = U u S\n")
                else:
                    return fail(
                        "Symbolic generation was requested but failed: "
                        f"{symbolic_result.error_message}"
                    )
            else:
                return fail(
                    "Symbolic generation was requested but KLEE is unavailable "
                    "locally and the prat-klee:latest image is not installed"
                )
        else:
            print("[2/8] Symbolic test generation not requested — T = U\n")

        workload_commands: list[list[str]] = []
        seen_commands: set[tuple[str, ...]] = set()
        for state in (True, False):
            for command in adapter.get_execution_commands(feature, state):
                key = tuple(command)
                if key not in seen_commands:
                    seen_commands.add(key)
                    workload_commands.append(command)
        workload_plan_id = test_plan_digest(workload_commands, symbolic_tests)

        # --- Algorithm 1 lines 4-5: B_all and L_all -----------------------
        if reuse_baseline and baseline_coverage_dir:
            print(f"[3/8] Reusing all-features baseline L_all from "
                  f"{baseline_coverage_dir}\n")
            enabled_coverage_dir = baseline_coverage_dir
        else:
            print(f"[3/8] Compiling with {feature} ENABLED...")
            result.checkpoint = WorkflowCheckpoint.COMPILE_ENABLED
            comp_enabled = _compile(
                adapter, project_path, feature, True, run_tests, build_system
            )
            result.compilation_enabled = comp_enabled
            if not comp_enabled.success:
                return fail(f"Compilation failed (enabled): {comp_enabled.error_message}")
            print(f"[+] Compilation successful ({comp_enabled.compilation_time:.2f}s)\n")

            print(f"[4/8] Collecting L_all with {feature} ENABLED...")
            result.checkpoint = WorkflowCheckpoint.COVERAGE_ENABLED
            cov_enabled = _coverage(
                adapter, project_path, feature, True, build_system,
                comp_enabled, output_dir, symbolic_tests,
                test_plan_id=workload_plan_id,
            )
            result.coverage_enabled = cov_enabled
            if not cov_enabled.success:
                return fail(f"Coverage generation failed (enabled): "
                            f"{cov_enabled.error_message}")
            if not cov_enabled.dynamic_execution:
                return fail(
                    "Coverage generation did not execute the test set T "
                    "for the enabled build"
                )
            print(f"[+] Generated {len(cov_enabled.coverage_files)} coverage file(s)\n")
            enabled_coverage_dir = cov_enabled.coverage_dir

        # --- Algorithm 1 lines 7-9: B_f and L_f ---------------------------
        print(f"[5/8] Compiling with {feature} DISABLED...")
        result.checkpoint = WorkflowCheckpoint.COMPILE_DISABLED
        comp_disabled = _compile(
            adapter, project_path, feature, False, run_tests, build_system
        )
        result.compilation_disabled = comp_disabled
        if not comp_disabled.success:
            # Algorithm 1: "we also discard build options that result in a
            # failed compilation". Surfaced as a failure so batch analysis can
            # record the option as discarded.
            return fail(f"Compilation failed (disabled): {comp_disabled.error_message}")
        print(f"[+] Compilation successful ({comp_disabled.compilation_time:.2f}s)\n")

        print(f"[6/8] Collecting L_f with {feature} DISABLED...")
        result.checkpoint = WorkflowCheckpoint.COVERAGE_DISABLED
        cov_disabled = _coverage(
            adapter, project_path, feature, False, build_system,
            comp_disabled, output_dir, symbolic_tests,
            test_plan_id=workload_plan_id,
        )
        result.coverage_disabled = cov_disabled
        if not cov_disabled.success:
            return fail(f"Coverage generation failed (disabled): "
                        f"{cov_disabled.error_message}")
        if not cov_disabled.dynamic_execution:
            return fail(
                "Coverage generation did not execute the test set T "
                "for the disabled build"
            )
        print(f"[+] Generated {len(cov_disabled.coverage_files)} coverage file(s)\n")

        # --- Algorithm 1 line 10: D_f = L_all \ L_f -----------------------
        print("[7/8] Mapping feature to code: D_f = L_all \\ L_f ...")
        result.checkpoint = WorkflowCheckpoint.MAP

        enabled_cov = load_coverage_dir(enabled_coverage_dir)
        disabled_cov = load_coverage_dir(cov_disabled.coverage_dir)

        if not enabled_cov:
            return fail(f"No parseable coverage in {enabled_coverage_dir}")
        if not disabled_cov:
            return fail(f"No parseable coverage in {cov_disabled.coverage_dir}")

        result.coverage_percent_enabled = coverage_percent(enabled_cov)
        result.coverage_percent_disabled = coverage_percent(disabled_cov)

        mapping = map_feature_from_coverage(feature, enabled_cov, disabled_cov)
        result.mapping = mapping

        extraction_result = extract_from_mapping(mapping)
        result.extraction_result = extraction_result
        result.checkpoint = WorkflowCheckpoint.EXTRACT

        print(f"[+] |D_f| = {extraction_result.total_removable_lines} line(s) "
              f"across {len(extraction_result.file_line_counts)} file(s)")
        if extraction_result.feature_only_removable_lines:
            print(f"    {extraction_result.feature_only_removable_lines} line(s) in "
                  f"{len(extraction_result.feature_only_file_counts)} dedicated "
                  f"feature file(s)")
        if extraction_result.excluded_never_executed:
            print(f"    {extraction_result.excluded_never_executed} never-executed "
                  f"line(s) retained (soundness over completeness)")
        if result.coverage_percent_enabled is not None:
            print(f"    Line coverage under T: "
                  f"{result.coverage_percent_enabled:.1f}% (all features)")
        print()

        # --- Reports ------------------------------------------------------
        print("[8/8] Generating reports...")
        _generate_reports(result, mapping, extraction_result, feature,
                          enabled_coverage_dir, cov_disabled.coverage_dir,
                          output_dir)

        # --- Steps 4-5: removal and testing -------------------------------
        if remove:
            result.checkpoint = WorkflowCheckpoint.REMOVE
            print(f"\n{'=' * 70}")
            print(f"Feature Removal: {feature}")
            print(f"{'=' * 70}")

            reference_outputs: dict[str, str] | None = None
            test_commands: list[list[str]] | None = None
            build_commands: list[list[str]] | None = None
            if adapter:
                test_commands = adapter.get_execution_commands(feature, False)
                build_commands = adapter.get_build_commands(
                    feature, False, with_coverage=False
                )

            if verify:
                try:
                    reference_outputs = capture_reference_outputs(
                        project_path,
                        adapter=adapter,
                        test_commands=test_commands,
                    )
                except RuntimeError as exc:
                    return fail(str(exc))
            removal_result = remove_feature_code(
                extraction_result,
                project_path,
                feature,
                protected_lines=mapping_protected(mapping),
                rebuild=not verify,
                build_commands=build_commands,
            )
            result.removal_result = removal_result

            if not removal_result.success:
                return fail(removal_result.error_message or "Feature removal failed")

            print(f"[+] Removed {removal_result.lines_removed} line(s)")

            if verify:
                result.checkpoint = WorkflowCheckpoint.VERIFY
                print(f"\n{'=' * 70}")
                print("Post-removal verification")
                print(f"{'=' * 70}")

                verification_result = verify_correctness(
                    project_path,
                    adapter=adapter,
                    build_commands=build_commands,
                    test_commands=test_commands,
                    symbolic_result=result.symbolic_result,
                    reference_outputs=reference_outputs,
                )
                result.verification_result = verification_result

                if not verification_result.success:
                    if removal_result.backup_dir:
                        removal_result.restored = restore_from_backup(
                            removal_result.backup_dir, project_path
                        )
                    return fail(
                        f"Post-removal verification failed: "
                        f"{verification_result.error_message or ''}"
                        f"{verification_result.total_tests_failed} test(s) failed"
                    )
                print("[+] Verification passed")

        result.success = True
        result.checkpoint = WorkflowCheckpoint.COMPLETE
        result.total_time = time.time() - start_time

        print(f"\n{'=' * 70}")
        print("WORKFLOW COMPLETE")
        print(f"{'=' * 70}")
        print(f"Total time: {result.total_time:.2f}s")
        print(f"Feature lines (|D_f|): {extraction_result.total_removable_lines}")
        print(f"Files analyzed: {len(extraction_result.file_line_counts)}")
        if extraction_result.html_report_path:
            print(f"HTML report: {extraction_result.html_report_path}")
        if extraction_result.dot_graph_path:
            print(f"DOT graph: {extraction_result.dot_graph_path}")
        if result.comparison_result and result.comparison_result.index_path:
            print(f"Comparison reports: {result.comparison_result.index_path}")
        print(f"{'=' * 70}\n")

        if not result.save_checkpoint(output_dir):
            result.success = False
            result.error_message = "Workflow completed but checkpoint could not be saved"
        return result

    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - checkpoint before surfacing
        return fail(f"Unexpected error: {exc}")


def _compile(
    adapter: ProjectAdapter | None,
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool,
    build_system: BuildSystem | None,
) -> CompilationResult:
    if adapter:
        return compile_with_adapter(adapter, feature, enabled, run_tests)
    return compile_project(
        project_path=project_path,
        feature=feature,
        enabled=enabled,
        run_tests=run_tests,
        build_system=build_system,
    )


def _coverage(
    adapter: ProjectAdapter | None,
    project_path: str,
    feature: str,
    enabled: bool,
    build_system: BuildSystem | None,
    compilation: CompilationResult,
    output_dir: str,
    symbolic_tests: list[str],
    test_plan_id: str | None = None,
) -> CoverageResult:
    if adapter:
        return generate_coverage_with_adapter(
            adapter, feature, enabled,
            output_dir=output_dir,
            symbolic_tests=symbolic_tests or None,
            test_plan_id=test_plan_id,
        )
    return generate_coverage(
        project_path=project_path,
        feature=feature,
        enabled=enabled,
        build_system=build_system or compilation.build_system,
    )


def _generate_reports(
    result: WorkflowResult,
    mapping: FeatureMapping,
    extraction_result: ExtractionResult,
    feature: str,
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
    output_dir: str,
) -> None:
    """Generate HTML/DOT/JSON reports and the paper's comparison reports.

    Reports are part of the review artifact. A missing rendering makes the run
    incomplete, so failures propagate to the workflow checkpoint.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    html_path = str(base / "report.html")
    generate_html_report(extraction_result, feature, output_path=html_path)
    extraction_result.html_report_path = html_path

    dot_path = str(base / "FDG.dot")
    generate_dot_graph(extraction_result, feature, output_path=dot_path)
    extraction_result.dot_graph_path = dot_path

    result.comparison_result = generate_comparison_reports(
        mapping,
        enabled_coverage_dir,
        disabled_coverage_dir,
        str(base),
    )

    generate_json_report(
        extraction_result, feature, output_path=str(base / "report.json")
    )
    print("[+] Reports generated\n")


def resume_workflow(
    checkpoint_file: str,
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: str | None = None,
) -> WorkflowResult:
    """Re-run the workflow, reporting which step a previous run reached.

    Genuine mid-pipeline resume is not supported: every stage after compilation
    depends on build artifacts that are not captured in the checkpoint, so
    restarting is the only sound option. The checkpoint still identifies the
    failing step.
    """
    print(f"\n[+] Resuming workflow from checkpoint: {checkpoint_file}\n")

    try:
        with open(checkpoint_file) as handle:
            checkpoint_data = json.load(handle)
        checkpoint = WorkflowCheckpoint(checkpoint_data["checkpoint"])
        print(f"[+] Previous run stopped at: {checkpoint.value}")
    except (OSError, KeyError, ValueError) as exc:
        print(f"[!] Could not read checkpoint: {exc}")

    print("[+] Re-running the full workflow (build artifacts are not "
          "checkpointed)\n")
    return run_complete_workflow(
        project_path=project_path,
        feature=feature,
        run_tests=run_tests,
        output_dir=output_dir,
    )
