"""
Whole-program feature analysis for PRAT — Algorithm 1 in full.

    D <- {}
    S <- SymbolicTestGeneration(P)
    T <- U u S
    B_all <- Compile(P)
    L_all <- CoverageAnalysis(B_all, T)
    for each f in F:
        P_f   <- DisableFeature(P, f)
        B_f   <- Compile(P_f)
        L_f   <- CoverageAnalysis(B_f, T)
        D_f   <- L_all \\ L_f
        D     <- D u {D_f}

Two properties of that algorithm this module preserves, and which a
per-feature loop over the single-feature workflow does not:

*n+1 builds, not 2n.* B_all is compiled once and L_all collected once, then
reused for every feature. Rebuilding the baseline per feature would both triple
the cost and, because coverage runs are not bit-identical, compare each feature
against a slightly different L_all.

*The baseline has all features enabled.* B_all enables every discovered feature
and B_i enables all but f_i, so D_i isolates f_i against a fully-featured
program rather than against whatever the project's defaults happen to be. A
failed B_all aborts the run; substituting project defaults would change
Algorithm 1's semantics.

Build options whose disabled build fails to compile are discarded, as the paper
specifies, and reported separately from options that mapped to zero lines.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .adapters import ProjectAdapter, get_adapter
from .compilation import (
    BuildSystem,
    CompilationResult,
    compile_project,
    compile_with_adapter,
)
from .coverage import (
    CoverageResult,
    generate_coverage,
    generate_coverage_with_adapter,
    test_plan_digest,
)
from .discovery import Feature, discover_features
from .extraction import ExtractionResult, extract_from_mapping
from .feature_graph import build_feature_graph, generate_feature_graph_html
from .gcov import load_coverage_dir
from .mapping import FeatureMapping, coverage_percent, map_feature_from_coverage
from .removal import RemovalResult, remove_feature_code, restore_from_backup
from .symbolic import (
    KleeConfig,
    SymbolicResult,
    check_klee_available,
    generate_symbolic_tests,
)
from .verification import (
    VerificationResult,
    capture_reference_outputs,
    verify_correctness,
)


@dataclass
class FeatureAnalysis:
    """Analysis result for a single feature."""

    feature: Feature
    mapping: FeatureMapping | None = None
    extraction: ExtractionResult | None = None
    removable_lines: int = 0
    affected_files: list[str] = field(default_factory=list)
    build_time: float = 0.0
    #: Set when this feature's build failed and the option was discarded.
    discarded_reason: str | None = None
    #: Pipeline stage responsible for a discarded or failed analysis.
    failure_stage: str | None = None
    coverage: CoverageResult | None = None
    #: Commands of T that could not run against this B_f (the feature's own
    #: tests, typically); they contributed no coverage to L_f.
    tests_not_run: list[str] = field(default_factory=list)

    @property
    def analyzed(self) -> bool:
        return self.discarded_reason is None and self.mapping is not None


@dataclass
class CrossFeatureMap:
    """Map of which files are shared across features."""

    file_to_features: dict[str, set[str]] = field(default_factory=dict)
    feature_to_files: dict[str, set[str]] = field(default_factory=dict)
    shared_files: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of Algorithm 1 across all discovered features."""

    success: bool
    project: str
    features_discovered: int
    features_analyzed: int
    features_failed: int
    total_removable_lines: int
    feature_results: dict[str, FeatureAnalysis] = field(default_factory=dict)
    cross_feature_map: CrossFeatureMap | None = None
    feature_graph_path: str | None = None
    total_time: float = 0.0
    error_message: str | None = None

    #: Build options discarded because their build failed, name -> reason.
    discarded_options: dict[str, str] = field(default_factory=dict)
    #: Number of compilations performed. Should be n+1 for n analyzed features.
    builds_performed: int = 0
    #: Whether B_all had every discovered feature enabled.
    baseline_all_features: bool = False
    baseline_note: str | None = None
    #: Line coverage achieved by T against B_all.
    baseline_coverage_percent: float | None = None
    baseline_coverage: CoverageResult | None = None
    symbolic_test_count: int = 0
    removal_result: RemovalResult | None = None
    verification_result: VerificationResult | None = None
    batch_checkpoint_path: str | None = None
    mapping_build_states: list[dict[str, bool]] = field(default_factory=list)
    run_id: str | None = None
    source_commit: str | None = None
    feature_names: list[str] = field(default_factory=list)
    #: Digest and size of the fixed test plan T run against every build.
    test_plan_id: str | None = None
    test_plan_commands: int | None = None

    @property
    def union_removable_lines(self) -> int:
        """|union of D_i| — lines removable when every feature is removed.

        This, not the sum of the per-feature counts, is what Table 4's
        "No features (PRAT)" column measures: a line attributed to two features
        must only be counted once.
        """
        union: set[tuple[str, int]] = set()
        for analysis in self.feature_results.values():
            if analysis.mapping is None:
                continue
            for path, file_map in analysis.mapping.files.items():
                union.update((path, line) for line in file_map.lines)
        return len(union)


def run_batch_analysis(
    project_path: str,
    output_dir: str | None = None,
    run_tests: bool = False,
    build_system: BuildSystem | None = None,
    adapter: ProjectAdapter | None = None,
    skip_features: list[str] | None = None,
    symbolic: bool = False,
    klee_config: KleeConfig | None = None,
    all_features_baseline: bool = True,
    remove: bool = False,
    verify: bool = True,
) -> BatchResult:
    """
    Run Algorithm 1 for every discovered feature in a project.

    Args:
        project_path: Path to project root.
        output_dir: Base directory for all output (default: project_path).
        run_tests: Run the project's test suite during compilation.
        build_system: Build system override (auto-detected if None).
        adapter: ProjectAdapter override (auto-detected if None).
        skip_features: Feature names to skip.
        symbolic: Generate the symbolic test set S and include it in T.
        klee_config: KLEE configuration; defaults to the paper's parameters.
        all_features_baseline: Compile B_all with every discovered feature
            enabled. Disable to use the project's default configuration as the
            baseline instead.
        remove: Remove the union of every successfully mapped D_f.
        verify: Rebuild and rerun the same test commands after union removal.

    Returns:
        BatchResult with per-feature mappings and a cross-feature map.
    """
    start_time = time.time()
    project_name = Path(project_path).name

    if output_dir is None:
        output_dir = project_path
    checkpoint_path = Path(output_dir) / "batch_checkpoint.json"
    checkpoint_path.unlink(missing_ok=True)

    skip_set = set(skip_features or ())

    print(f"\n{'=' * 70}")
    print(f"PRAT Batch Analysis (Algorithm 1): {project_name}")
    print(f"{'=' * 70}\n")

    if adapter is None:
        adapter = get_adapter(project_path)
    if adapter is None:
        return _finalize_batch_result(BatchResult(
            success=False,
            project=project_name,
            features_discovered=0,
            features_analyzed=0,
            features_failed=0,
            total_removable_lines=0,
            total_time=time.time() - start_time,
            error_message=(
                "No project adapter can execute and validate this build system; "
                "refusing to produce compile-only coverage"
            ),
        ), output_dir, start_time)

    # --- F <- feature identification ---------------------------------------
    print("[1] Discovering features...")
    features = discover_features(project_path, adapter=adapter)

    if not features:
        return _finalize_batch_result(BatchResult(
            success=False,
            project=project_name,
            features_discovered=0,
            features_analyzed=0,
            features_failed=0,
            total_removable_lines=0,
            total_time=time.time() - start_time,
            error_message="No features discovered",
        ), output_dir, start_time)

    active = [f for f in features if f.name not in skip_set]

    print(f"    Found {len(features)} feature(s)"
          f"{f' (skipping {len(skip_set)})' if skip_set else ''}")
    for feature in features:
        status = "SKIP" if feature.name in skip_set else "ANALYZE"
        description = f" — {feature.description}" if feature.description else ""
        print(f"      [{status}] {feature.name}{description}")

    if not active:
        return _finalize_batch_result(BatchResult(
            success=False,
            project=project_name,
            features_discovered=len(features),
            features_analyzed=0,
            features_failed=0,
            total_removable_lines=0,
            total_time=time.time() - start_time,
            error_message="All discovered features were skipped",
        ), output_dir, start_time)

    result = BatchResult(
        success=False,
        project=project_name,
        features_discovered=len(features),
        features_analyzed=0,
        features_failed=0,
        total_removable_lines=0,
        run_id=os.environ.get("PRAT_RUN_ID") or str(uuid.uuid4()),
    )

    # --- S <- SymbolicTestGeneration(P); T <- U u S -------------------------
    symbolic_tests: list[str] = []
    symbolic_result_obj: SymbolicResult | None = None
    if symbolic:
        if adapter.build_system == BuildSystem.CARGO:
            result.error_message = (
                "The KLEE symbolic-test path supports C/C++ LLVM bitcode, not "
                "Cargo/Rust projects; refusing to label this run as the full "
                "paper algorithm"
            )
            return _finalize_batch_result(result, output_dir, start_time)
        print("\n[2] Generating symbolic test set S (KLEE)...")
        local = check_klee_available(use_docker=False)
        if local or check_klee_available(use_docker=True):
            symbolic_result = generate_symbolic_tests(
                project_path=project_path,
                config=klee_config,
                output_dir=str(Path(output_dir) / "klee_tests"),
                use_docker=not local,
                replay=False,
            )
            symbolic_result_obj = symbolic_result
            if symbolic_result.success:
                symbolic_tests = list(symbolic_result.test_cases)
                result.symbolic_test_count = symbolic_result.test_count
                print(f"    Generated {symbolic_result.test_count} test case(s); "
                      f"T = U u S")
            else:
                result.error_message = (
                    "Symbolic generation was requested but failed: "
                    f"{symbolic_result.error_message}"
                )
                return _finalize_batch_result(result, output_dir, start_time)
        else:
            result.error_message = (
                "Symbolic generation was requested but KLEE is unavailable "
                "locally and the prat-klee:latest image is not installed"
            )
            return _finalize_batch_result(result, output_dir, start_time)
    else:
        print("\n[2] Symbolic test generation not requested — T = U")

    all_names = [f.name for f in active]
    result.feature_names = list(all_names)
    result.source_commit = _git_commit(project_path)
    # Algorithm 1 line 3: T is fixed once, then run unchanged against B_all
    # and every B_f (lines 5 and 9). The adapter supplies a plan that does not
    # depend on any single feature's polarity.
    fixed_test_commands = (
        [list(c) for c in adapter.get_test_plan(all_names)] if adapter else []
    )
    plan_commands = fixed_test_commands or (
        [["adapter-managed-coverage-tests"]]
        if adapter and adapter.coverage_command_executes_tests()
        else []
    )
    workload_plan_id = test_plan_digest(plan_commands, symbolic_tests)
    result.test_plan_id = workload_plan_id
    result.test_plan_commands = len(fixed_test_commands)

    # --- B_all <- Compile(P); L_all <- CoverageAnalysis(B_all, T) -----------
    print("\n[3] Building baseline B_all and collecting L_all...")
    baseline_cov, baseline_note, used_all = _build_baseline(
        adapter, project_path, all_names, run_tests, build_system,
        output_dir, symbolic_tests, all_features_baseline,
        execution_commands=fixed_test_commands,
        test_plan_id=workload_plan_id,
    )
    result.mapping_build_states.append(
        {name: True for name in all_names}
        if all_features_baseline
        else {}
    )
    result.builds_performed += 1
    result.baseline_all_features = used_all
    result.baseline_note = baseline_note
    result.baseline_coverage = baseline_cov

    if baseline_cov is None:
        result.error_message = baseline_note or "Baseline build failed"
        print(f"    [!] {result.error_message}")
        return _finalize_batch_result(result, output_dir, start_time)

    baseline_coverage = load_coverage_dir(baseline_cov.coverage_dir)
    if not baseline_coverage:
        result.error_message = (
            f"No parseable coverage in baseline {baseline_cov.coverage_dir}"
        )
        print(f"    [!] {result.error_message}")
        return _finalize_batch_result(result, output_dir, start_time)

    result.baseline_coverage_percent = coverage_percent(baseline_coverage)
    print(f"    L_all: {sum(len(c.executed) for c in baseline_coverage.values())} "
          f"executed line(s) across {len(baseline_coverage)} file(s)")
    if result.baseline_coverage_percent is not None:
        print(f"    Line coverage under T: {result.baseline_coverage_percent:.1f}%")
    if baseline_note:
        print(f"    Note: {baseline_note}")

    # --- for each f in F: D_f <- L_all \ L_f --------------------------------
    print(f"\n[4] Per-feature analysis ({len(active)} features, "
          f"one build each)...\n")

    feature_results: dict[str, FeatureAnalysis] = {}
    result.feature_results = feature_results

    for index, feature in enumerate(active, start=1):
        print(f"{'-' * 50}")
        print(f"[{index}/{len(active)}] {feature.name}")
        print(f"{'-' * 50}")

        analysis = FeatureAnalysis(feature=feature)
        feature_results[feature.name] = analysis
        feature_start = time.time()

        states = _leave_one_out(all_names, feature.name) if used_all else None

        compilation = _compile(
            adapter, project_path, feature.name, False,
            run_tests, build_system, states,
        )
        result.mapping_build_states.append(dict(states or {}))
        result.builds_performed += 1

        if not compilation.success:
            # Algorithm 1: discard build options that fail to compile.
            reason = compilation.error_message or "compilation failed"
            analysis.discarded_reason = reason
            analysis.failure_stage = "compilation"
            result.discarded_options[feature.name] = reason
            result.features_failed += 1
            print(f"    [!] Discarded — build failed: {reason.splitlines()[0][:160]}")
            continue

        cov = _coverage(
            adapter, project_path, feature.name, False, build_system,
            compilation, output_dir, symbolic_tests, states,
            execution_commands=fixed_test_commands,
            test_plan_id=workload_plan_id,
            allow_test_failures=True,
        )
        analysis.coverage = cov

        if not cov.success:
            reason = cov.error_message or "coverage generation failed"
            analysis.discarded_reason = reason
            analysis.failure_stage = "coverage"
            result.features_failed += 1
            result.error_message = (
                f"Coverage failed for {feature.name}; the batch is incomplete: "
                f"{reason}"
            )
            print(f"    [!] {result.error_message}")
            return _finalize_batch_result(result, output_dir, start_time)
        if not cov.dynamic_execution:
            reason = "coverage did not execute the test set T"
            analysis.discarded_reason = reason
            analysis.failure_stage = "execution"
            result.features_failed += 1
            result.error_message = (
                f"Coverage failed for {feature.name}; {reason}"
            )
            print(f"    [!] {result.error_message}")
            return _finalize_batch_result(result, output_dir, start_time)
        if cov.test_plan_id != (
            result.baseline_coverage.test_plan_id
            if result.baseline_coverage
            else workload_plan_id
        ):
            reason = "the test plan run against B_f differs from the one run against B_all"
            analysis.discarded_reason = reason
            analysis.failure_stage = "execution"
            result.features_failed += 1
            result.error_message = f"Coverage failed for {feature.name}; {reason}"
            print(f"    [!] {result.error_message}")
            return _finalize_batch_result(result, output_dir, start_time)
        if cov.execution_errors:
            analysis.tests_not_run = list(cov.execution_errors)
            print(f"    {len(cov.execution_errors)} test command(s) in T could "
                  f"not run against B_{feature.name} (no coverage contributed)")

        disabled_coverage = load_coverage_dir(cov.coverage_dir)
        if not disabled_coverage:
            analysis.discarded_reason = "coverage contained no parseable files"
            analysis.failure_stage = "coverage"
            result.features_failed += 1
            result.error_message = (
                f"Coverage failed for {feature.name}; no parseable files"
            )
            return _finalize_batch_result(result, output_dir, start_time)
        mapping = map_feature_from_coverage(
            feature.name, baseline_coverage, disabled_coverage
        )
        extraction = extract_from_mapping(mapping)

        analysis.mapping = mapping
        analysis.extraction = extraction
        analysis.removable_lines = extraction.total_removable_lines
        analysis.affected_files = sorted(extraction.file_line_counts)
        analysis.build_time = time.time() - feature_start

        result.features_analyzed += 1
        result.total_removable_lines += extraction.total_removable_lines

        print(f"    |D_f| = {extraction.total_removable_lines} line(s) across "
              f"{len(extraction.file_line_counts)} file(s) "
              f"({analysis.build_time:.1f}s)")

    result.feature_results = feature_results

    # --- Cross-feature map and feature graph -------------------------------
    print("\n[5] Building cross-feature dependency map...")
    result.cross_feature_map = _build_cross_feature_map(feature_results)

    if result.features_analyzed:
        try:
            graph = build_feature_graph(result)
            graph_path = str(Path(output_dir) / "feature_graph.html")
            generate_feature_graph_html(graph, graph_path)
            result.feature_graph_path = graph_path
        except Exception as exc:  # noqa: BLE001 - graph is a view, not the result
            result.error_message = f"Failed to generate feature graph: {exc}"
            print(f"    [!] {result.error_message}")
            return _finalize_batch_result(result, output_dir, start_time)

    if remove:
        if adapter is None:
            result.error_message = "Batch union removal requires a project adapter"
            return _finalize_batch_result(result, output_dir, start_time)

        union = _union_extraction(feature_results)
        disabled_states = {name: False for name in all_names}
        print("\n[6] Building all-features-disabled reference configuration...")
        reference_build = compile_with_adapter(
            adapter,
            all_names[0],
            False,
            run_tests=False,
            feature_states=disabled_states,
            with_coverage=False,
        )
        result.builds_performed += 1
        if not reference_build.success:
            result.error_message = (
                "Could not build the all-features-disabled reference: "
                f"{reference_build.error_message}"
            )
            return _finalize_batch_result(result, output_dir, start_time)

        test_commands = _all_feature_test_commands(adapter, all_names)
        try:
            references = capture_reference_outputs(
                project_path,
                adapter=adapter,
                test_commands=test_commands,
            )
        except RuntimeError as exc:
            result.error_message = str(exc)
            return _finalize_batch_result(result, output_dir, start_time)

        build_commands = adapter.get_build_commands_for_set(
            disabled_states, with_coverage=False
        )
        print(f"\n[7] Removing union D ({union.total_removable_lines} lines)...")
        result.removal_result = remove_feature_code(
            union,
            project_path,
            "ALL_SELECTED_FEATURES",
            rebuild=not verify,
            build_commands=build_commands,
        )
        if not result.removal_result.success:
            result.error_message = result.removal_result.error_message
            return _finalize_batch_result(result, output_dir, start_time)

        if verify:
            print("\n[8] Verifying union removal...")
            result.verification_result = verify_correctness(
                project_path,
                adapter=adapter,
                build_commands=build_commands,
                test_commands=test_commands,
                symbolic_result=symbolic_result_obj,
                reference_outputs=references,
            )
            if not result.verification_result.success:
                if result.removal_result.backup_dir:
                    result.removal_result.restored = restore_from_backup(
                        result.removal_result.backup_dir, project_path
                    )
                result.error_message = (
                    "Union removal verification failed: "
                    f"{result.verification_result.error_message or ''}"
                )
                return _finalize_batch_result(result, output_dir, start_time)

    result.total_time = time.time() - start_time
    result.success = (
        result.features_analyzed > 0
        and (result.baseline_all_features or not all_features_baseline)
    )

    _print_summary(result, len(active))
    return _finalize_batch_result(result, output_dir, start_time)


def _union_extraction(
    feature_results: dict[str, FeatureAnalysis],
) -> ExtractionResult:
    """Merge per-feature mappings into the exact union used for removal."""
    numbers: dict[str, set[int]] = {}
    contents: dict[str, dict[int, str]] = {}
    feature_only: set[str] = set()

    for analysis in feature_results.values():
        extraction = analysis.extraction
        if extraction is None:
            continue
        for path, lines in extraction.file_line_numbers.items():
            numbers.setdefault(path, set()).update(lines)
            path_contents = contents.setdefault(path, {})
            for line, text in zip(
                lines, extraction.file_line_content.get(path, [])
            ):
                path_contents.setdefault(line, text)
        feature_only.update(extraction.feature_only_source_paths)

    ordered = {path: sorted(lines) for path, lines in sorted(numbers.items())}
    counts = {path: len(lines) for path, lines in ordered.items()}
    return ExtractionResult(
        success=True,
        file_line_counts=counts,
        total_removable_lines=sum(counts.values()),
        file_line_numbers=ordered,
        file_line_content={
            path: [contents.get(path, {}).get(line, "") for line in lines]
            for path, lines in ordered.items()
        },
        feature_only_source_paths=sorted(feature_only),
        feature_only_file_counts={
            path: counts[path] for path in feature_only if path in counts
        },
        feature_only_removable_lines=sum(
            counts[path] for path in feature_only if path in counts
        ),
    )


def _all_feature_test_commands(
    adapter: ProjectAdapter,
    features: list[str],
) -> list[list[str]]:
    """Union adapter test commands without running duplicates."""
    commands: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for feature in features:
        for enabled in (True, False):
            for command in adapter.get_execution_commands(feature, enabled):
                key = tuple(command)
                if key not in seen:
                    seen.add(key)
                    commands.append(command)
    return commands


def _finalize_batch_result(
    result: BatchResult,
    output_dir: str,
    start_time: float,
) -> BatchResult:
    """Finish timing and persist success or failure evidence."""
    result.total_time = time.time() - start_time
    try:
        result.batch_checkpoint_path = _save_batch_checkpoint(result, output_dir)
    except OSError as exc:
        result.success = False
        checkpoint_error = f"batch checkpoint could not be saved: {exc}"
        result.error_message = (
            f"{result.error_message}; {checkpoint_error}"
            if result.error_message
            else checkpoint_error
        )
    return result


def _save_batch_checkpoint(result: BatchResult, output_dir: str) -> str:
    """Persist reviewer-readable evidence without embedding source text."""
    path = Path(output_dir) / "batch_checkpoint.json"
    data = {
        "success": result.success,
        "project": result.project,
        "features_discovered": result.features_discovered,
        "features_analyzed": result.features_analyzed,
        "features_failed": result.features_failed,
        "builds_performed": result.builds_performed,
        "mapping_build_states": result.mapping_build_states,
        "run_id": result.run_id,
        "source_commit": result.source_commit,
        "feature_names": result.feature_names,
        "test_plan_id": result.test_plan_id,
        "test_plan_commands": result.test_plan_commands,
        "baseline_all_features": result.baseline_all_features,
        "baseline_coverage_percent": result.baseline_coverage_percent,
        "baseline_coverage": (
            asdict(result.baseline_coverage)
            if result.baseline_coverage
            else None
        ),
        "symbolic_test_count": result.symbolic_test_count,
        "sum_removable_lines": result.total_removable_lines,
        "union_removable_lines": result.union_removable_lines,
        "discarded_options": result.discarded_options,
        "features": {
            name: {
                "analyzed": analysis.analyzed,
                "removable_lines": analysis.removable_lines,
                "affected_files": analysis.affected_files,
                "discarded_reason": analysis.discarded_reason,
                "failure_stage": analysis.failure_stage,
                "tests_not_run": analysis.tests_not_run,
                "coverage": (
                    asdict(analysis.coverage) if analysis.coverage else None
                ),
            }
            for name, analysis in result.feature_results.items()
        },
        "removal_result": (
            asdict(result.removal_result) if result.removal_result else None
        ),
        "verification_result": (
            asdict(result.verification_result)
            if result.verification_result
            else None
        ),
        "error_message": result.error_message,
        "total_time": result.total_time,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)
    return str(path)


def _git_commit(project_path: str) -> str | None:
    """Read the analyzed source revision when the project is a git checkout."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _leave_one_out(all_names: list[str], excluded: str) -> dict[str, bool]:
    """Feature states for B_i: every feature enabled except ``excluded``."""
    return {name: (name != excluded) for name in all_names}


def _build_baseline(
    adapter: ProjectAdapter | None,
    project_path: str,
    all_names: list[str],
    run_tests: bool,
    build_system: BuildSystem | None,
    output_dir: str,
    symbolic_tests: list[str],
    all_features_baseline: bool,
    execution_commands: list[list[str]] | None = None,
    test_plan_id: str | None = None,
) -> tuple[CoverageResult | None, str | None, bool]:
    """Compile B_all and collect L_all.

    Returns ``(coverage_result, note, used_all_features)``. The requested
    baseline is strict: a B_all failure is not replaced with project defaults.
    """
    if all_features_baseline:
        if adapter is None:
            return (
                None,
                "An adapter with explicit feature-set support is required for B_all",
                False,
            )
        attempts: list[tuple[dict[str, bool] | None, bool, str]] = [
            ({name: True for name in all_names}, True, "all features enabled")
        ]
    else:
        attempts = [(None, False, "project default configuration")]

    for states, used_all, description in attempts:
        print(f"    Compiling baseline ({description})...")
        compilation = _compile(
            adapter, project_path, all_names[0], True,
            run_tests, build_system, states,
        )

        if not compilation.success:
            first = (compilation.error_message or "").splitlines()
            detail = first[0][:160] if first else "unknown error"
            print(f"    [!] Baseline build failed ({description}): {detail}")
            continue

        cov = _coverage(
            adapter, project_path, all_names[0], True, build_system,
            compilation, output_dir, symbolic_tests, states,
            label="all_features" if used_all else "baseline_defaults",
            execution_commands=execution_commands,
            test_plan_id=test_plan_id,
        )

        if not cov.success:
            print(f"    [!] Baseline coverage failed ({description}): "
                  f"{cov.error_message}")
            continue
        if not cov.dynamic_execution:
            print(f"    [!] Baseline coverage was not dynamic ({description})")
            continue

        return cov, None, used_all

    requested = "all-features B_all" if all_features_baseline else "default baseline"
    return None, f"{requested} build or coverage failed", False


def _compile(
    adapter: ProjectAdapter | None,
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool,
    build_system: BuildSystem | None,
    feature_states: dict[str, bool] | None,
) -> CompilationResult:
    if adapter:
        return compile_with_adapter(
            adapter, feature, enabled, run_tests, feature_states=feature_states
        )
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
    feature_states: dict[str, bool] | None,
    label: str | None = None,
    execution_commands: list[list[str]] | None = None,
    test_plan_id: str | None = None,
    allow_test_failures: bool = False,
) -> CoverageResult:
    if adapter:
        return generate_coverage_with_adapter(
            adapter, feature, enabled,
            output_dir=output_dir,
            symbolic_tests=symbolic_tests or None,
            feature_states=feature_states,
            label=label,
            execution_commands=execution_commands,
            test_plan_id=test_plan_id,
            allow_test_failures=allow_test_failures,
        )
    return generate_coverage(
        project_path=project_path,
        feature=feature,
        enabled=enabled,
        build_system=build_system or compilation.build_system,
    )


def _build_cross_feature_map(
    feature_results: dict[str, FeatureAnalysis],
) -> CrossFeatureMap:
    """Map which source files are attributed to more than one feature.

    The paper notes that in its dataset "there have not been instances of
    multiple features utilizing or overlapping the same code blocks"; this makes
    that property checkable per run rather than assumed.
    """
    cmap = CrossFeatureMap()

    for name, analysis in feature_results.items():
        if not analysis.analyzed:
            continue
        files = set(analysis.affected_files)
        cmap.feature_to_files[name] = files
        for path in files:
            cmap.file_to_features.setdefault(path, set()).add(name)

    names = sorted(cmap.feature_to_files)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            shared = cmap.feature_to_files[first] & cmap.feature_to_files[second]
            if shared:
                cmap.shared_files[f"{first} & {second}"] = sorted(shared)

    return cmap


def _print_summary(result: BatchResult, active_count: int) -> None:
    print(f"\n{'=' * 70}")
    print("BATCH ANALYSIS COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Features discovered:  {result.features_discovered}")
    print(f"  Features analyzed:    {result.features_analyzed}")
    print(f"  Options discarded:    {result.features_failed}")
    print(f"  Builds performed:     {result.builds_performed} "
          f"(Algorithm 1 expects n+1 = {active_count + 1})")
    print(f"  Baseline:             "
          f"{'all features enabled' if result.baseline_all_features else 'project defaults'}")
    if result.baseline_coverage_percent is not None:
        print(f"  Baseline coverage:    {result.baseline_coverage_percent:.1f}%")
    print(f"  Sum of |D_f|:         {result.total_removable_lines}")
    print(f"  |union of D_f|:       {result.union_removable_lines} "
          f"(lines removable with all features removed)")
    print(f"  Total time:           {result.total_time:.1f}s")
    if result.feature_graph_path:
        print(f"  Feature graph:        {result.feature_graph_path}")

    if result.baseline_note:
        print(f"\n  Baseline note: {result.baseline_note}")

    if result.discarded_options:
        print("\n  Discarded build options (failed to compile):")
        for name, reason in sorted(result.discarded_options.items()):
            print(f"    {name}: {reason.splitlines()[0][:120]}")

    cmap = result.cross_feature_map
    if cmap and cmap.shared_files:
        print("\n  Files attributed to multiple features:")
        for pair, files in sorted(cmap.shared_files.items()):
            print(f"    {pair}: {len(files)} shared file(s)")
    elif cmap:
        print("\n  No source file was attributed to more than one feature.")

    print("\n  Per-feature breakdown:")
    for name, analysis in sorted(
        result.feature_results.items(),
        key=lambda item: item[1].removable_lines,
        reverse=True,
    ):
        if analysis.discarded_reason:
            print(f"    - {name:25s} discarded")
        else:
            print(f"    + {name:25s} {analysis.removable_lines:6d} line(s)  "
                  f"({len(analysis.affected_files)} file(s))")
    print()
