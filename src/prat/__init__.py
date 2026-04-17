"""
PRAT (Protocol Representation and Analysis Toolkit)

A modular toolkit for identifying and removing feature-specific code
from C/C++ projects using compile-time coverage analysis.
"""

__version__ = "2.0.0"

# Import main modules
from . import environment
from . import compilation
from . import coverage
from . import diff
from . import extraction
from . import reporting
from . import workflow
from . import discovery
from . import adapters
from . import removal
from . import batch
from . import feature_graph

# Import key classes and functions
from .environment import setup_environment, verify_dependencies
from .compilation import compile_project, compile_with_adapter, detect_build_system, CompilationResult, BuildSystem
from .coverage import generate_coverage, generate_coverage_with_adapter, organize_coverage_files, CoverageResult
from .diff import diff_coverage_files, match_coverage_files, DiffResult
from .extraction import extract_features, count_removable_lines, ExtractionResult
from .reporting import generate_html_report, generate_dot_graph, generate_html_diffs, generate_json_report
from .workflow import run_complete_workflow, resume_workflow, WorkflowResult, WorkflowCheckpoint
from .discovery import discover_features, discover_features_cmake, discover_features_autotools, discover_features_cargo, discover_features_make, Feature
from .removal import remove_feature_code, restore_from_backup, RemovalResult
from .batch import run_batch_analysis, BatchResult
from .feature_graph import build_feature_graph, build_feature_graph_from_single, generate_feature_graph_html, FeatureGraph
from .adapters import ProjectAdapter, MosquittoAdapter, FFmpegAdapter, RustAdapter, CMakeAdapter, get_adapter

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
