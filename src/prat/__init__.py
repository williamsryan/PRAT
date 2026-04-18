"""
PRAT (Protocol Representation and Analysis Toolkit)

A modular toolkit for identifying and removing feature-specific code
from C/C++ projects using compile-time coverage analysis.
"""

__version__ = "0.2.0"

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
    removal,
    reporting,
    symbolic,
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
from .diff import DiffResult, diff_coverage_files, match_coverage_files
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
from .extraction import ExtractionResult, count_removable_lines, extract_features
from .feature_graph import (
    FeatureGraph,
    build_feature_graph,
    build_feature_graph_from_single,
    generate_feature_graph_html,
)
from .removal import RemovalResult, remove_feature_code, restore_from_backup
from .reporting import (
    generate_dot_graph,
    generate_html_diffs,
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
from .verification import VerificationResult, verify_correctness
from .workflow import WorkflowCheckpoint, WorkflowResult, resume_workflow, run_complete_workflow

__all__ = [
    'environment',
    'compilation',
    'coverage',
    'diff',
    'extraction',
    'reporting',
    'workflow',
    'discovery',
    'adapters',
    'setup_environment',
    'verify_dependencies',
    'compile_project',
    'compile_with_adapter',
    'detect_build_system',
    'generate_coverage',
    'generate_coverage_with_adapter',
    'organize_coverage_files',
    'diff_coverage_files',
    'match_coverage_files',
    'extract_features',
    'count_removable_lines',
    'generate_html_report',
    'generate_dot_graph',
    'generate_html_diffs',
    'run_complete_workflow',
    'resume_workflow',
    'discover_features',
    'discover_features_cmake',
    'discover_features_autotools',
    'discover_features_cargo',
    'discover_features_make',
    'CompilationResult',
    'CoverageResult',
    'DiffResult',
    'ExtractionResult',
    'WorkflowResult',
    'WorkflowCheckpoint',
    'Feature',
    'BuildSystem',
    'ProjectAdapter',
    'MosquittoAdapter',
    'FFmpegAdapter',
    'RustAdapter',
    'CMakeAdapter',
    'get_adapter',
]
