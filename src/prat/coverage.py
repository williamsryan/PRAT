#!/usr/bin/env python3
"""
Coverage generation module for PRAT.

This module handles generation and organization of gcov/llvm-cov coverage files
from compiled binaries with instrumentation.
"""

import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .compilation import BuildSystem


@dataclass
class CoverageResult:
    """Result of coverage generation operation."""
    success: bool
    coverage_files: List[str]
    coverage_dir: str
    missing_files: List[str]
    error_message: Optional[str] = None


def generate_coverage(
    project_path: str,
    feature: str,
    enabled: bool,
    build_system: BuildSystem,
    coverage_tool: str = "auto"
) -> CoverageResult:
    """
    Run gcov/llvm-cov on compiled source files.
    
    Args:
        project_path: Path to project root
        feature: Feature name
        enabled: Whether feature was enabled during compilation
        build_system: Build system used for compilation
        coverage_tool: Coverage tool to use ("gcov", "llvm-cov-9", or "auto")
    
    Returns:
        CoverageResult with paths to generated .gcov files
    """
    # Auto-detect coverage tool if needed
    if coverage_tool == "auto":
        coverage_tool = _detect_coverage_tool()
    
    coverage_files = []
    missing_files = []
    
    try:
        # Generate coverage based on build system
        if build_system == BuildSystem.MAKE:
            coverage_files, missing_files = _generate_coverage_make(
                project_path, coverage_tool
            )
        elif build_system == BuildSystem.CMAKE:
            coverage_files, missing_files = _generate_coverage_cmake(
                project_path, coverage_tool
            )
        elif build_system == BuildSystem.AUTOTOOLS:
            coverage_files, missing_files = _generate_coverage_autotools(
                project_path, coverage_tool
            )
        elif build_system == BuildSystem.CARGO:
            coverage_files, missing_files = _generate_coverage_cargo(
                project_path, coverage_tool
            )
        else:
            return CoverageResult(
                success=False,
                coverage_files=[],
                coverage_dir="",
                missing_files=[],
                error_message=f"Unsupported build system: {build_system}"
            )
        
        # Organize coverage files
        flag = "yes" if enabled else "no"
        coverage_dir = organize_coverage_files(
            coverage_files, feature, enabled, os.getcwd()
        )
        
        success = len(coverage_files) > 0
        error_message = None
        
        if not success:
            error_message = "No coverage files were generated"
        elif missing_files:
            print(f"[!] Warning: {len(missing_files)} files failed to generate coverage")
        
        return CoverageResult(
            success=success,
            coverage_files=coverage_files,
            coverage_dir=coverage_dir,
            missing_files=missing_files,
            error_message=error_message
        )
        
    except Exception as e:
        return CoverageResult(
            success=False,
            coverage_files=[],
            coverage_dir="",
            missing_files=[],
            error_message=f"Coverage generation failed: {str(e)}"
        )


def organize_coverage_files(
    coverage_files: List[str],
    feature: str,
    enabled: bool,
    output_dir: str
) -> str:
    """
    Move coverage files to organized directory structure.
    
    Args:
        coverage_files: List of paths to .gcov files
        feature: Feature name
        enabled: Whether feature was enabled
        output_dir: Base output directory
    
    Returns:
        Path to coverage directory
    """
    flag = "yes" if enabled else "no"
    coverage_dir_name = f"coverage_files_WITH_{feature.upper()}_{flag}"
    coverage_dir = Path(output_dir) / coverage_dir_name
    
    # Create coverage directory
    coverage_dir.mkdir(parents=True, exist_ok=True)
    
    # Move coverage files
    moved_files = []
    for cov_file in coverage_files:
        cov_path = Path(cov_file)
        if cov_path.exists():
            dest = coverage_dir / cov_path.name
            try:
                shutil.move(str(cov_path), str(dest))
                moved_files.append(str(dest))
            except Exception as e:
                print(f"[!] Failed to move {cov_file}: {e}")
    
    print(f"[+] Organized {len(moved_files)} coverage files in {coverage_dir}")
    
    return str(coverage_dir)


def _detect_coverage_tool() -> str:
    """Detect which coverage tool is available."""
    if shutil.which("llvm-cov-9"):
        return "llvm-cov-9"
    elif shutil.which("gcov"):
        return "gcov"
    else:
        raise RuntimeError("No coverage tool found (gcov or llvm-cov-9)")


def _generate_coverage_make(
    project_path: str,
    coverage_tool: str
) -> tuple[List[str], List[str]]:
    """Generate coverage for Make-based projects (e.g., Mosquitto)."""
    coverage_files = []
    missing_files = []
    
    # Run coverage on src and lib directories
    src_dir = Path(project_path) / "src"
    lib_dir = Path(project_path) / "lib"
    
    for directory in [src_dir, lib_dir]:
        if not directory.exists():
            continue
        
        # Run coverage tool
        if coverage_tool == "llvm-cov-9":
            cmd = "llvm-cov-9 gcov *"
        else:
            cmd = "gcov *"
        
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=directory,
            capture_output=True,
            text=True
        )
        
        # Collect generated .gcov files
        for item in directory.iterdir():
            if item.suffix == ".gcov":
                coverage_files.append(str(item))
    
    return coverage_files, missing_files


def _generate_coverage_cmake(
    project_path: str,
    coverage_tool: str
) -> tuple[List[str], List[str]]:
    """Generate coverage for CMake-based projects."""
    coverage_files = []
    missing_files = []
    
    build_dir = Path(project_path) / "build"
    
    if not build_dir.exists():
        return coverage_files, missing_files
    
    # Find all .gcda files and run gcov on them
    for gcda_file in build_dir.rglob("*.gcda"):
        parent_dir = gcda_file.parent
        
        if coverage_tool == "llvm-cov-9":
            cmd = f"llvm-cov-9 gcov {gcda_file.name}"
        else:
            cmd = f"gcov {gcda_file.name}"
        
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=parent_dir,
            capture_output=True,
            text=True
        )
        
        # Collect generated .gcov files
        for item in parent_dir.iterdir():
            if item.suffix == ".gcov":
                coverage_files.append(str(item))
    
    return coverage_files, missing_files


def _generate_coverage_autotools(
    project_path: str,
    coverage_tool: str
) -> tuple[List[str], List[str]]:
    """Generate coverage for Autotools-based projects (e.g., FFmpeg)."""
    coverage_files = []
    missing_files = []
    
    project_path = Path(project_path)
    
    # FFmpeg-specific directories
    lib_dirs = ["libavcodec", "libavfilter", "libavformat"]
    
    for lib_dir in lib_dirs:
        lib_path = project_path / lib_dir
        if not lib_path.exists():
            continue
        
        # Run coverage tool
        if coverage_tool == "llvm-cov-9":
            cmd = f"llvm-cov-9 gcov {lib_dir}/*"
        else:
            cmd = f"gcov {lib_dir}/*"
        
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=project_path,
            capture_output=True,
            text=True
        )
        
        # Collect generated .gcov files from project root
        for item in project_path.iterdir():
            if item.suffix == ".gcov":
                coverage_files.append(str(item))
    
    return coverage_files, missing_files


def _generate_coverage_cargo(
    project_path: str,
    coverage_tool: str
) -> tuple[List[str], List[str]]:
    """Generate coverage for Cargo-based Rust projects."""
    coverage_files = []
    missing_files = []
    
    deps_dir = Path(project_path) / "target" / "debug" / "deps"
    
    if not deps_dir.exists():
        return coverage_files, missing_files
    
    # Run coverage tool
    if coverage_tool == "llvm-cov-9":
        cmd = "llvm-cov-9 gcov *"
    else:
        cmd = "gcov-9 *"
    
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=deps_dir,
        capture_output=True,
        text=True
    )
    
    # Collect generated .gcov files
    for item in deps_dir.iterdir():
        if item.suffix == ".gcov":
            coverage_files.append(str(item))
    
    return coverage_files, missing_files
