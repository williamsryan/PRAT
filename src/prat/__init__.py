"""
PRAT (Protocol Representation and Analysis Toolkit)

A modular toolkit for identifying and removing feature-specific code
from C/C++/Rust projects using differential dynamic coverage analysis.
"""

__version__ = "2.0.0"

# Import main modules
from . import (
    adapters,
    batch,
    compilation,
    coverage,
    diff,
    discovery,
    environment,
    extraction,
    feature_graph,
    fuzzing,
    gcov,
    mapping,
    removal,
    reporting,
    symbolic,
    variants,
    verification,
    workflow,
)
from .adapters import (
    CMakeAdapter,
    FFmpegAdapter,
    MosquittoAdapter,
    ProjectAdapter,
    RustAdapter,
    get_adapter,
)
from .batch import BatchResult, run_batch_analysis
from .compilation import (
    BuildSystem,
    CompilationResult,
    compile_project,
    compile_with_adapter,
    detect_build_system,
)
from .coverage import (
    CoverageResult,
    generate_coverage,
    generate_coverage_with_adapter,
    organize_coverage_files,
)
from .diff import (
    ComparisonResult,
    generate_comparison_reports,
    generate_coverage_comparison,
    generate_source_comparison,
)
from .discovery import (
    Feature,
    discover_features,
    discover_features_autotools,
    discover_features_cargo,
    discover_features_cmake,
    discover_features_make,
)

# Import key classes and functions
from .environment import setup_environment, verify_dependencies
from .extraction import ExtractionResult, extract_features, extract_from_mapping
from .feature_graph import (
    FeatureGraph,
    build_feature_graph,
    build_feature_graph_from_single,
    generate_feature_graph_html,
)
from .fuzzing import (
    FuzzCampaign,
    FuzzResult,
    check_boofuzz_available,
    compare_to_baseline,
    fuzz_variant,
)
from .gcov import (
    GcovFile,
    load_coverage_dir,
    merge_contiguous,
    parse_gcov,
    parse_tool_function_output,
)
from .mapping import (
    FeatureMapping,
    FileMapping,
    coverage_percent,
    function_percent,
    map_feature,
    map_feature_from_coverage,
    protected_lines,
)
from .removal import (
    RemovalResult,
    plan_removal,
    remove_feature_code,
    restore_from_backup,
)
from .reporting import (
    generate_dot_graph,
    generate_html_report,
    generate_json_report,
)
from .symbolic import (
    KleeConfig,
    SymbolicResult,
    check_klee_available,
    compile_to_bytecode,
    generate_symbolic_tests,
    replay_tests,
    run_klee,
)
from .variants import Variant, VariantChain, build_variant_chain
from .verification import (
    VerificationResult,
    VerificationStatus,
    capture_reference_outputs,
    verify_correctness,
)
from .workflow import WorkflowCheckpoint, WorkflowResult, resume_workflow, run_complete_workflow

__all__ = [
    "adapters",
    "batch",
    "compilation",
    "coverage",
    "diff",
    "discovery",
    "environment",
    "extraction",
    "feature_graph",
    "fuzzing",
    "gcov",
    "mapping",
    "removal",
    "reporting",
    "symbolic",
    "variants",
    "verification",
    "workflow",
    "BatchResult",
    "BuildSystem",
    "CMakeAdapter",
    "CompilationResult",
    "CoverageResult",
    "ComparisonResult",
    "ExtractionResult",
    "Feature",
    "FeatureGraph",
    "FeatureMapping",
    "FuzzCampaign",
    "FuzzResult",
    "FileMapping",
    "GcovFile",
    "FFmpegAdapter",
    "KleeConfig",
    "MosquittoAdapter",
    "ProjectAdapter",
    "RemovalResult",
    "RustAdapter",
    "SymbolicResult",
    "Variant",
    "VariantChain",
    "VerificationResult",
    "VerificationStatus",
    "WorkflowCheckpoint",
    "WorkflowResult",
    "build_feature_graph",
    "build_feature_graph_from_single",
    "check_klee_available",
    "compile_project",
    "compile_to_bytecode",
    "compile_with_adapter",
    "detect_build_system",
    "discover_features",
    "discover_features_autotools",
    "discover_features_cargo",
    "discover_features_cmake",
    "discover_features_make",
    "extract_features",
    "extract_from_mapping",
    "generate_coverage",
    "generate_coverage_with_adapter",
    "generate_dot_graph",
    "generate_feature_graph_html",
    "generate_html_report",
    "generate_json_report",
    "generate_symbolic_tests",
    "build_variant_chain",
    "capture_reference_outputs",
    "check_boofuzz_available",
    "compare_to_baseline",
    "coverage_percent",
    "generate_comparison_reports",
    "generate_coverage_comparison",
    "generate_source_comparison",
    "function_percent",
    "fuzz_variant",
    "get_adapter",
    "load_coverage_dir",
    "map_feature",
    "map_feature_from_coverage",
    "merge_contiguous",
    "parse_gcov",
    "parse_tool_function_output",
    "plan_removal",
    "protected_lines",
    "organize_coverage_files",
    "remove_feature_code",
    "replay_tests",
    "restore_from_backup",
    "resume_workflow",
    "run_batch_analysis",
    "run_complete_workflow",
    "run_klee",
    "setup_environment",
    "verify_correctness",
    "verify_dependencies",
]
