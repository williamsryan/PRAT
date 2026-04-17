"""
Workflow orchestration module for PRAT.

This module coordinates the complete end-to-end analysis workflow,
including compilation, coverage generation, diffing, and extraction.
"""

import time
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

from .compilation import compile_project, compile_with_adapter, CompilationResult, BuildSystem
from .coverage import generate_coverage, generate_coverage_with_adapter, organize_coverage_files, CoverageResult
from .diff import diff_coverage_files, DiffResult
from .extraction import extract_features, ExtractionResult
from .environment import verify_dependencies
from .reporting import generate_html_report, generate_dot_graph, generate_html_diffs, generate_json_report
from .adapters import get_adapter, ProjectAdapter


class WorkflowCheckpoint(Enum):
    """Workflow checkpoints for resume functionality."""
    START = "start"
    COMPILE_ENABLED = "compile_enabled"
    COVERAGE_ENABLED = "coverage_enabled"
    COMPILE_DISABLED = "compile_disabled"
    COVERAGE_DISABLED = "coverage_disabled"
    DIFF = "diff"
    EXTRACT = "extract"
    COMPLETE = "complete"


@dataclass
class WorkflowResult:
    """Result of complete workflow execution."""
    success: bool
    project: str
    feature: str
    compilation_enabled: Optional[CompilationResult]
    compilation_disabled: Optional[CompilationResult]
    coverage_enabled: Optional[CoverageResult]
    coverage_disabled: Optional[CoverageResult]
    diff_result: Optional[DiffResult]
    extraction_result: Optional[ExtractionResult]
    total_time: float
    checkpoint: WorkflowCheckpoint
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result['checkpoint'] = self.checkpoint.value
        return result
    
    def save_checkpoint(self, output_dir: str):
        """
        Save workflow state to checkpoint file.
        
        Args:
            output_dir: Directory to save checkpoint
        """
        checkpoint_file = Path(output_dir) / "workflow_checkpoint.json"
        
        try:
            with open(checkpoint_file, 'w') as f:
                json.dump(self.to_dict(), f, indent=2, default=str)
            print(f"[+] Checkpoint saved to {checkpoint_file}")
        except Exception as e:
            print(f"[!] Failed to save checkpoint: {e}")


def run_complete_workflow(
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: Optional[str] = None,
    build_system: Optional[BuildSystem] = None,
    adapter: Optional[ProjectAdapter] = None
) -> WorkflowResult:
    """
    Execute complete PRAT analysis workflow.
    
    Workflow steps:
    1. Verify environment dependencies
    2. Compile with feature enabled
    3. Generate coverage (enabled)
    4. Compile with feature disabled
    5. Generate coverage (disabled)
    6. Diff coverage files
    7. Extract features
    8. Generate reports
    
    Args:
        project_path: Path to project root directory
        feature: Feature name to analyze
        run_tests: Whether to run test suite after compilation
        output_dir: Directory for output files (default: project_path)
        build_system: Build system to use (auto-detected if None)
        adapter: ProjectAdapter to use (auto-detected if None).
                 When provided, overrides build_system and uses adapter paths.
        
    Returns:
        WorkflowResult with all outputs and statistics
    """
    start_time = time.time()
    
    if output_dir is None:
        output_dir = project_path
    
    project_name = Path(project_path).name
    
    print(f"\n{'='*70}")
    print(f"PRAT Workflow: {project_name} - Feature: {feature}")
    print(f"{'='*70}\n")
    
    # Initialize result
    result = WorkflowResult(
        success=False,
        project=project_name,
        feature=feature,
        compilation_enabled=None,
        compilation_disabled=None,
        coverage_enabled=None,
        coverage_disabled=None,
        diff_result=None,
        extraction_result=None,
        total_time=0.0,
        checkpoint=WorkflowCheckpoint.START
    )
    
    try:
        # Step 1: Verify environment
        print("[1/8] Verifying environment dependencies...")
        deps = verify_dependencies()
        missing = deps.missing_tools

        if missing:
            error_msg = f"Missing dependencies: {', '.join(missing)}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.checkpoint = WorkflowCheckpoint.START
            result.save_checkpoint(output_dir)
            return result
        
        print("[+] All dependencies verified\n")
        
        # Use provided adapter or auto-detect
        if adapter is None:
            adapter = get_adapter(project_path)
        if adapter:
            print(f"[+] Detected project adapter: {type(adapter).__name__}")
            print(f"    Build system: {adapter.build_system.value}")
            print(f"    Coverage tool: {adapter.coverage_tool}")
            print(f"    Source dirs: {', '.join(adapter.source_directories)}\n")
        else:
            print("[+] No project-specific adapter found — using generic pipeline\n")

        # Step 2: Compile with feature enabled
        print(f"[2/8] Compiling with {feature} ENABLED...")
        result.checkpoint = WorkflowCheckpoint.COMPILE_ENABLED
        
        if adapter:
            comp_enabled = compile_with_adapter(adapter, feature, True, run_tests)
        else:
            comp_enabled = compile_project(
                project_path=project_path,
                feature=feature,
                enabled=True,
                run_tests=run_tests,
                build_system=build_system
            )
        result.compilation_enabled = comp_enabled
        
        if not comp_enabled.success:
            error_msg = f"Compilation failed (enabled): {comp_enabled.error_message}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.save_checkpoint(output_dir)
            return result
        
        print(f"[+] Compilation successful ({comp_enabled.compilation_time:.2f}s)\n")
        
        # Step 3: Generate coverage (enabled)
        print(f"[3/8] Generating coverage with {feature} ENABLED...")
        result.checkpoint = WorkflowCheckpoint.COVERAGE_ENABLED
        
        if adapter:
            cov_enabled = generate_coverage_with_adapter(adapter, feature, True)
        else:
            cov_enabled = generate_coverage(
                project_path=project_path,
                feature=feature,
                enabled=True,
                build_system=build_system if build_system else comp_enabled.build_system
            )
        result.coverage_enabled = cov_enabled
        
        if not cov_enabled.success:
            error_msg = f"Coverage generation failed (enabled): {cov_enabled.error_message}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.save_checkpoint(output_dir)
            return result
        
        print(f"[+] Generated {len(cov_enabled.coverage_files)} coverage files\n")
        
        # Step 4: Compile with feature disabled
        print(f"[4/8] Compiling with {feature} DISABLED...")
        result.checkpoint = WorkflowCheckpoint.COMPILE_DISABLED
        
        if adapter:
            comp_disabled = compile_with_adapter(adapter, feature, False, run_tests)
        else:
            comp_disabled = compile_project(
                project_path=project_path,
                feature=feature,
                enabled=False,
                run_tests=run_tests,
                build_system=build_system
            )
        result.compilation_disabled = comp_disabled
        
        if not comp_disabled.success:
            error_msg = f"Compilation failed (disabled): {comp_disabled.error_message}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.save_checkpoint(output_dir)
            return result
        
        print(f"[+] Compilation successful ({comp_disabled.compilation_time:.2f}s)\n")
        
        # Step 5: Generate coverage (disabled)
        print(f"[5/8] Generating coverage with {feature} DISABLED...")
        result.checkpoint = WorkflowCheckpoint.COVERAGE_DISABLED
        
        if adapter:
            cov_disabled = generate_coverage_with_adapter(adapter, feature, False)
        else:
            cov_disabled = generate_coverage(
                project_path=project_path,
                feature=feature,
                enabled=False,
                build_system=build_system if build_system else comp_disabled.build_system
            )
        result.coverage_disabled = cov_disabled
        
        if not cov_disabled.success:
            error_msg = f"Coverage generation failed (disabled): {cov_disabled.error_message}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.save_checkpoint(output_dir)
            return result
        
        print(f"[+] Generated {len(cov_disabled.coverage_files)} coverage files\n")
        
        # Step 6: Diff coverage files
        print("[6/8] Diffing coverage files...")
        result.checkpoint = WorkflowCheckpoint.DIFF
        
        diff_result = diff_coverage_files(
            enabled_dir=cov_enabled.coverage_dir,
            disabled_dir=cov_disabled.coverage_dir,
            feature=feature,
            output_dir=output_dir
        )
        result.diff_result = diff_result
        
        if not diff_result.success:
            error_msg = f"Diff generation failed: {diff_result.error_message}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.save_checkpoint(output_dir)
            return result
        
        print(f"[+] Generated {diff_result.total_diffs} diff files\n")
        
        # Step 7: Extract features
        print("[7/8] Extracting feature-specific code...")
        result.checkpoint = WorkflowCheckpoint.EXTRACT
        
        extraction_result = extract_features(
            diff_dir=diff_result.diff_dir,
            feature=feature,
            output_dir=output_dir
        )
        result.extraction_result = extraction_result
        
        if not extraction_result.success:
            error_msg = f"Feature extraction failed: {extraction_result.error_message}"
            print(f"[!] {error_msg}")
            result.error_message = error_msg
            result.save_checkpoint(output_dir)
            return result
        
        print(f"[+] Identified {extraction_result.total_removable_lines} removable lines\n")
        
        # Step 8: Generate reports
        print("[8/8] Generating reports...")
        try:
            report_base = output_dir if output_dir else project_path
            
            html_path = str(Path(report_base) / "report.html")
            generate_html_report(extraction_result, feature, output_path=html_path)
            extraction_result.html_report_path = html_path
            
            dot_path = str(Path(report_base) / "FDG.dot")
            generate_dot_graph(extraction_result, feature, output_path=dot_path)
            extraction_result.dot_graph_path = dot_path
            
            # Generate HTML diffs (optional — requires pygmentize)
            generate_html_diffs(diff_result.diff_dir,
                              str(Path(report_base) / "reports"))

            # Generate JSON report (machine-readable)
            json_path = str(Path(report_base) / "report.json")
            generate_json_report(extraction_result, feature, output_path=json_path)
            
            print("[+] Reports generated\n")
        except Exception as e:
            print(f"[!] Report generation failed (non-fatal): {e}\n")
        
        # Workflow complete
        result.success = True
        result.checkpoint = WorkflowCheckpoint.COMPLETE
        result.total_time = time.time() - start_time
        
        # Print summary
        print(f"\n{'='*70}")
        print("WORKFLOW COMPLETE")
        print(f"{'='*70}")
        print(f"Total time: {result.total_time:.2f}s")
        print(f"Removable lines: {extraction_result.total_removable_lines}")
        print(f"Files analyzed: {len(extraction_result.file_line_counts)}")
        
        if extraction_result.html_report_path:
            print(f"HTML report: {extraction_result.html_report_path}")
        if extraction_result.dot_graph_path:
            print(f"DOT graph: {extraction_result.dot_graph_path}")
        
        print(f"{'='*70}\n")
        
        # Save final checkpoint
        result.save_checkpoint(output_dir)
        
        return result
        
    except Exception as e:
        # Handle unexpected errors
        error_msg = f"Unexpected error: {str(e)}"
        print(f"\n[!] {error_msg}")
        
        result.error_message = error_msg
        result.total_time = time.time() - start_time
        result.save_checkpoint(output_dir)
        
        return result


def resume_workflow(
    checkpoint_file: str,
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: Optional[str] = None
) -> WorkflowResult:
    """
    Resume workflow from a checkpoint after error.
    
    Checkpoints: compile_enabled, coverage_enabled, compile_disabled,
                coverage_disabled, diff, extract
    
    Args:
        checkpoint_file: Path to checkpoint JSON file
        project_path: Path to project root directory
        feature: Feature name to analyze
        run_tests: Whether to run test suite
        output_dir: Directory for output files
        
    Returns:
        WorkflowResult from resumed execution
    """
    print(f"\n[+] Resuming workflow from checkpoint: {checkpoint_file}\n")
    
    try:
        with open(checkpoint_file, 'r') as f:
            checkpoint_data = json.load(f)
        
        checkpoint = WorkflowCheckpoint(checkpoint_data['checkpoint'])
        print(f"[+] Last checkpoint: {checkpoint.value}")
        
        # For now, just run complete workflow
        # TODO: Implement actual resume logic based on checkpoint
        print("[!] Resume functionality not fully implemented yet")
        print("[+] Running complete workflow instead...\n")
        
        return run_complete_workflow(
            project_path=project_path,
            feature=feature,
            run_tests=run_tests,
            output_dir=output_dir
        )
        
    except Exception as e:
        print(f"[!] Failed to resume from checkpoint: {e}")
        print("[+] Running complete workflow instead...\n")
        
        return run_complete_workflow(
            project_path=project_path,
            feature=feature,
            run_tests=run_tests,
            output_dir=output_dir
        )
