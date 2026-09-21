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
program rather than against whatever the project's defaults happen to be. When
the all-features build does not compile — mutually exclusive options make this
possible, and the paper reports discarding such options — the baseline falls
back to project defaults and the result records that it did.

Build options whose disabled build fails to compile are discarded, as the paper
specifies, and reported separately from options that mapped to zero lines.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
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
)
from .discovery import Feature, discover_features
from .extraction import ExtractionResult, extract_from_mapping
from .feature_graph import build_feature_graph, generate_feature_graph_html
from .gcov import load_coverage_dir
from .mapping import FeatureMapping, coverage_percent, map_feature_from_coverage
from .symbolic import KleeConfig, check_klee_available, generate_symbolic_tests


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
    symbolic_test_count: int = 0

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

    Returns:
        BatchResult with per-feature mappings and a cross-feature map.
    """
    start_time = time.time()
    project_name = Path(project_path).name

    if output_dir is None:
        output_dir = project_path

    skip_set = set(skip_features or ())

    print(f"\n{'=' * 70}")
    print(f"PRAT Batch Analysis (Algorithm 1): {project_name}")
    print(f"{'=' * 70}\n")

    if adapter is None:
        adapter = get_adapter(project_path)

    # --- F <- feature identification ---------------------------------------
    print("[1] Discovering features...")
    features = discover_features(project_path)

    if not features:
        return BatchResult(
            success=False,
            project=project_name,
            features_discovered=0,
            features_analyzed=0,
            features_failed=0,
            total_removable_lines=0,
            total_time=time.time() - start_time,
            error_message="No features discovered",
        )

    active = [f for f in features if f.name not in skip_set]

    print(f"    Found {len(features)} feature(s)"
          f"{f' (skipping {len(skip_set)})' if skip_set else ''}")
    for feature in features:
        status = "SKIP" if feature.name in skip_set else "ANALYZE"
        description = f" — {feature.description}" if feature.description else ""
        print(f"      [{status}] {feature.name}{description}")

    if not active:
        return BatchResult(
            success=False,
            project=project_name,
            features_discovered=len(features),
            features_analyzed=0,
            features_failed=0,
            total_removable_lines=0,
            total_time=time.time() - start_time,
            error_message="All discovered features were skipped",
        )

    result = BatchResult(
        success=False,
        project=project_name,
        features_discovered=len(features),
        features_analyzed=0,
        features_failed=0,
        total_removable_lines=0,
    )

    # --- S <- SymbolicTestGeneration(P); T <- U u S -------------------------
    symbolic_tests: list[str] = []
    if symbolic:
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
            if symbolic_result.success:
                symbolic_tests = list(symbolic_result.test_cases)
                result.symbolic_test_count = symbolic_result.test_count
                print(f"    Generated {symbolic_result.test_count} test case(s); "
                      f"T = U u S")
            else:
                print(f"    Symbolic generation failed, T = U only: "
                      f"{symbolic_result.error_message}")
        else:
            print("    KLEE not available — T = U only")
    else:
        print("\n[2] Symbolic test generation not requested — T = U")

    all_names = [f.name for f in active]

    # --- B_all <- Compile(P); L_all <- CoverageAnalysis(B_all, T) -----------
    print("\n[3] Building baseline B_all and collecting L_all...")
    baseline_cov, baseline_note, used_all = _build_baseline(
        adapter, project_path, all_names, run_tests, build_system,
        output_dir, symbolic_tests, all_features_baseline,
    )
    result.builds_performed += 1
    result.baseline_all_features = used_all
    result.baseline_note = baseline_note

    if baseline_cov is None:
        result.error_message = baseline_note or "Baseline build failed"
        result.total_time = time.time() - start_time
        print(f"    [!] {result.error_message}")
        return result

    baseline_coverage = load_coverage_dir(baseline_cov)
    if not baseline_coverage:
        result.error_message = f"No parseable coverage in baseline {baseline_cov}"
        result.total_time = time.time() - start_time
        print(f"    [!] {result.error_message}")
        return result

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
        result.builds_performed += 1

        if not compilation.success:
            # Algorithm 1: discard build options that fail to compile.
            reason = compilation.error_message or "compilation failed"
            analysis.discarded_reason = reason
            result.discarded_options[feature.name] = reason
            result.features_failed += 1
            print(f"    [!] Discarded — build failed: {reason.splitlines()[0][:160]}")
            continue

        cov = _coverage(
            adapter, project_path, feature.name, False, build_system,
            compilation, output_dir, symbolic_tests, states,
        )

        if not cov.success:
            reason = cov.error_message or "coverage generation failed"
            analysis.discarded_reason = reason
            result.discarded_options[feature.name] = reason
            result.features_failed += 1
            print(f"    [!] Discarded — coverage failed: {reason}")
            continue

        disabled_coverage = load_coverage_dir(cov.coverage_dir)
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
            print(f"    [!] Failed to generate feature graph: {exc}")

    result.total_time = time.time() - start_time
    result.success = result.features_analyzed > 0

    _print_summary(result, len(active))
    return result


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
) -> tuple[str | None, str | None, bool]:
    """Compile B_all and collect L_all.

    Returns ``(coverage_dir, note, used_all_features)``. When the all-features
    build fails, retries with the project's default configuration and explains
    the fallback in ``note`` so the result is not silently a different baseline.
    """
    attempts: list[tuple[dict[str, bool] | None, bool, str]] = []
    if all_features_baseline and adapter is not None:
        attempts.append(
            ({name: True for name in all_names}, True, "all features enabled")
        )
    attempts.append((None, False, "project default configuration"))

    fallback_note: str | None = None

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
            if used_all:
                fallback_note = (
                    "B_all with all features enabled did not compile "
                    f"({detail}); baseline fell back to the project default "
                    "configuration, so D_f isolates each feature against "
                    "defaults rather than against a fully-featured build"
                )
            continue

        cov = _coverage(
            adapter, project_path, all_names[0], True, build_system,
            compilation, output_dir, symbolic_tests, states,
            label="all_features" if used_all else "baseline_defaults",
        )

        if not cov.success:
            print(f"    [!] Baseline coverage failed ({description}): "
                  f"{cov.error_message}")
            continue

        note = None if used_all else fallback_note
        return cov.coverage_dir, note, used_all

    return None, fallback_note or "Baseline build failed for all attempts", False


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
) -> CoverageResult:
    if adapter:
        return generate_coverage_with_adapter(
            adapter, feature, enabled,
            output_dir=output_dir,
            symbolic_tests=symbolic_tests or None,
            feature_states=feature_states,
            label=label,
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
