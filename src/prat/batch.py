"""
Batch analysis module for PRAT.

Implements Algorithm 1 from the paper: discover all features, then
run the complete analysis pipeline for each one, producing a cross-feature
dependency map and aggregate report.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .adapters import ProjectAdapter, get_adapter
from .compilation import BuildSystem
from .discovery import Feature, discover_features
from .feature_graph import build_feature_graph, generate_feature_graph_html
from .workflow import WorkflowResult, run_complete_workflow


@dataclass
class FeatureAnalysis:
    """Analysis result for a single feature."""
    feature: Feature
    workflow_result: Optional[WorkflowResult] = None
    removable_lines: int = 0
    affected_files: List[str] = field(default_factory=list)


@dataclass
class CrossFeatureMap:
    """Map of which files are shared across features."""
    # file_name -> set of feature names that affect it
    file_to_features: Dict[str, Set[str]] = field(default_factory=dict)
    # feature_name -> set of file names it affects
    feature_to_files: Dict[str, Set[str]] = field(default_factory=dict)
    # Pairs of features that share files
    shared_files: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of batch analysis across all features."""
    success: bool
    project: str
    features_discovered: int
    features_analyzed: int
    features_failed: int
    total_removable_lines: int
    feature_results: Dict[str, FeatureAnalysis] = field(default_factory=dict)
    cross_feature_map: Optional[CrossFeatureMap] = None
    feature_graph_path: Optional[str] = None
    total_time: float = 0.0
    error_message: Optional[str] = None


def run_batch_analysis(
    project_path: str,
    output_dir: Optional[str] = None,
    run_tests: bool = False,
    build_system: Optional[BuildSystem] = None,
    adapter: Optional[ProjectAdapter] = None,
    skip_features: Optional[List[str]] = None,
) -> BatchResult:
    """
    Run PRAT analysis for ALL discovered features in a project.

    Paper Algorithm 1: Build n+1 versions (all-features baseline +
    one-per-feature-disabled), collect coverage, identify per-feature code.

    Args:
        project_path: Path to project root
        output_dir: Base directory for all output (default: project_path)
        run_tests: Whether to run test suites during coverage
        build_system: Build system override (auto-detected if None)
        adapter: ProjectAdapter override (auto-detected if None)
        skip_features: Feature names to skip

    Returns:
        BatchResult with per-feature results and cross-feature map
    """
    start_time = time.time()
    project_name = Path(project_path).name

    if output_dir is None:
        output_dir = project_path

    skip_set = set(skip_features) if skip_features else set()

    print(f"\n{'='*70}")
    print(f"PRAT Batch Analysis: {project_name}")
    print(f"{'='*70}\n")

    # Auto-detect adapter if not provided
    if adapter is None:
        adapter = get_adapter(project_path)

    # Step 1: Discover all features
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

    # Filter out skipped features
    active_features = [f for f in features if f.name not in skip_set]

    print(f"    Found {len(features)} features"
          f"{f' (skipping {len(skip_set)})' if skip_set else ''}")
    for f in features:
        status = "SKIP" if f.name in skip_set else "ANALYZE"
        desc = f" — {f.description}" if f.description else ""
        print(f"      [{status}] {f.name}{desc}")

    print(f"\n[2] Running per-feature analysis ({len(active_features)} features)...\n")

    # Step 2: Analyze each feature
    feature_results: Dict[str, FeatureAnalysis] = {}
    analyzed = 0
    failed = 0
    total_lines = 0

    for i, feat in enumerate(active_features, 1):
        feat_name = feat.name
        feat_output = str(Path(output_dir) / f"feature_{feat_name}")
        Path(feat_output).mkdir(parents=True, exist_ok=True)

        print(f"\n{'─'*50}")
        print(f"[{i}/{len(active_features)}] Analyzing feature: {feat_name}")
        print(f"{'─'*50}")

        try:
            wf_result = run_complete_workflow(
                project_path=project_path,
                feature=feat_name,
                run_tests=run_tests,
                output_dir=feat_output,
                build_system=build_system,
                adapter=adapter,
            )

            fa = FeatureAnalysis(feature=feat, workflow_result=wf_result)

            if wf_result.success and wf_result.extraction_result:
                fa.removable_lines = wf_result.extraction_result.total_removable_lines
                fa.affected_files = list(
                    wf_result.extraction_result.file_line_counts.keys()
                )
                total_lines += fa.removable_lines
                analyzed += 1
            else:
                failed += 1
                print(f"    [!] Failed: {wf_result.error_message}")

            feature_results[feat_name] = fa

        except Exception as e:
            failed += 1
            feature_results[feat_name] = FeatureAnalysis(feature=feat)
            print(f"    [!] Exception: {e}")

    # Step 3: Build cross-feature dependency map
    print("\n[3] Building cross-feature dependency map...")
    cross_map = _build_cross_feature_map(feature_results)

    graph_path = None
    if analyzed:
        try:
            graph = build_feature_graph(
                BatchResult(
                    success=True,
                    project=project_name,
                    features_discovered=len(features),
                    features_analyzed=analyzed,
                    features_failed=failed,
                    total_removable_lines=total_lines,
                    feature_results=feature_results,
                    cross_feature_map=cross_map,
                )
            )
            graph_path = str(Path(output_dir) / "feature_graph.html")
            generate_feature_graph_html(graph, graph_path)
        except Exception as e:
            print(f"    [!] Failed to generate feature graph: {e}")

    # Print summary
    elapsed = time.time() - start_time

    print(f"\n{'='*70}")
    print("BATCH ANALYSIS COMPLETE")
    print(f"{'='*70}")
    print(f"  Features discovered: {len(features)}")
    print(f"  Features analyzed:   {analyzed}")
    print(f"  Features failed:     {failed}")
    print(f"  Total removable LoC: {total_lines}")
    print(f"  Total time:          {elapsed:.1f}s")
    if graph_path:
        print(f"  Feature graph:       {graph_path}")

    if cross_map.shared_files:
        print("\n  Cross-feature file sharing:")
        for pair, files in sorted(cross_map.shared_files.items()):
            print(f"    {pair}: {len(files)} shared files")

    print("\n  Per-feature breakdown:")
    for name, fa in sorted(
        feature_results.items(),
        key=lambda x: x[1].removable_lines,
        reverse=True,
    ):
        status = "✓" if fa.workflow_result and fa.workflow_result.success else "✗"
        print(f"    {status} {name:25s} {fa.removable_lines:6d} lines  "
              f"({len(fa.affected_files)} files)")

    return BatchResult(
        success=failed < len(active_features),  # At least one succeeded
        project=project_name,
        features_discovered=len(features),
        features_analyzed=analyzed,
        features_failed=failed,
        total_removable_lines=total_lines,
        feature_results=feature_results,
        cross_feature_map=cross_map,
        feature_graph_path=graph_path,
        total_time=elapsed,
    )


def _build_cross_feature_map(
    feature_results: Dict[str, FeatureAnalysis],
) -> CrossFeatureMap:
    """
    Build a map of cross-feature file dependencies.

    Identifies which source files are affected by multiple features,
    indicating shared code that needs careful handling during removal.
    """
    cmap = CrossFeatureMap()

    for feat_name, fa in feature_results.items():
        files = set(fa.affected_files)
        cmap.feature_to_files[feat_name] = files

        for f in files:
            if f not in cmap.file_to_features:
                cmap.file_to_features[f] = set()
            cmap.file_to_features[f].add(feat_name)

    # Find feature pairs that share files
    feat_names = list(cmap.feature_to_files.keys())
    for i, f1 in enumerate(feat_names):
        for f2 in feat_names[i + 1:]:
            shared = cmap.feature_to_files.get(f1, set()) & \
                     cmap.feature_to_files.get(f2, set())
            if shared:
                pair_key = f"{f1} ∩ {f2}"
                cmap.shared_files[pair_key] = sorted(shared)

    return cmap
