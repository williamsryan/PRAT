#!/usr/bin/env python3
"""
Compilation module for PRAT.

This module handles project compilation with feature flags enabled/disabled,
supporting multiple build systems (Make, CMake, Autotools, Cargo).
"""

import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, List


class BuildSystem(Enum):
    """Supported build systems."""
    MAKE = "make"
    CMAKE = "cmake"
    AUTOTOOLS = "autotools"
    CARGO = "cargo"
    UNKNOWN = "unknown"


@dataclass
class CompilationResult:
    """Result of a compilation operation."""
    success: bool
    binary_path: Optional[str]
    error_message: Optional[str]
    compilation_time: float
    coverage_enabled: bool
    build_system: BuildSystem


def detect_build_system(project_path: str) -> BuildSystem:
    """
    Detect project build system from project files.
    
    Args:
        project_path: Path to project root directory
        
    Returns:
        BuildSystem enum value indicating detected build system
    """
    project_path = Path(project_path)
    
    # Check for Cargo.toml (Rust)
    if (project_path / "Cargo.toml").exists():
        return BuildSystem.CARGO
    
    # Check for CMakeLists.txt (CMake)
    if (project_path / "CMakeLists.txt").exists():
        return BuildSystem.CMAKE
    
    # Check for configure script (Autotools)
    if (project_path / "configure").exists():
        return BuildSystem.AUTOTOOLS
    
    # Check for Makefile (Make)
    if (project_path / "Makefile").exists():
        return BuildSystem.MAKE
    
    return BuildSystem.UNKNOWN


def compile_project(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool = False,
    build_system: Optional[BuildSystem] = None
) -> CompilationResult:
    """
    Compile project with specified feature flag.
    
    Args:
        project_path: Path to project root
        feature: Feature name (e.g., "TLS", "BRIDGE")
        enabled: True for feature enabled, False for disabled
        run_tests: Whether to run test suite after compilation
        build_system: Build system to use (auto-detected if None)
    
    Returns:
        CompilationResult with status, binary path, and error messages
    """
    start_time = time.time()
    
    # Auto-detect build system if not specified
    if build_system is None:
        build_system = detect_build_system(project_path)
    
    if build_system == BuildSystem.UNKNOWN:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message="Unable to detect build system",
            compilation_time=0.0,
            coverage_enabled=False,
            build_system=build_system
        )
    
    # Dispatch to appropriate compilation function
    try:
        if build_system == BuildSystem.MAKE:
            result = _compile_make(project_path, feature, enabled, run_tests)
        elif build_system == BuildSystem.CMAKE:
            result = _compile_cmake(project_path, feature, enabled, run_tests)
        elif build_system == BuildSystem.AUTOTOOLS:
            result = _compile_autotools(project_path, feature, enabled, run_tests)
        elif build_system == BuildSystem.CARGO:
            result = _compile_cargo(project_path, feature, enabled, run_tests)
        else:
            return CompilationResult(
                success=False,
                binary_path=None,
                error_message=f"Unsupported build system: {build_system}",
                compilation_time=0.0,
                coverage_enabled=False,
                build_system=build_system
            )
        
        compilation_time = time.time() - start_time
        result.compilation_time = compilation_time
        result.build_system = build_system
        
        return result
        
    except Exception as e:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"Compilation failed: {str(e)}",
            compilation_time=time.time() - start_time,
            coverage_enabled=False,
            build_system=build_system
        )


def _compile_make(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool
) -> CompilationResult:
    """Compile Make-based project (e.g., Mosquitto)."""
    flag = "yes" if enabled else "no"
    target = f"WITH_{feature.upper()}={flag}"
    
    # Clean previous build
    clean_proc = subprocess.run(
        ["make", "clean"],
        cwd=project_path,
        capture_output=True,
        text=True
    )
    
    # Compile with coverage enabled
    compile_proc = subprocess.run(
        ["make", "binary", "-j", "WITH_COVERAGE=yes", target],
        cwd=project_path,
        capture_output=True,
        text=True
    )
    
    if compile_proc.returncode != 0:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"Make compilation failed: {compile_proc.stderr}",
            compilation_time=0.0,
            coverage_enabled=True,
            build_system=BuildSystem.MAKE
        )
    
    # Run tests if requested
    if run_tests:
        test_proc = subprocess.run(
            ["make", "utest", "-j", "WITH_COVERAGE=yes"],
            cwd=project_path,
            capture_output=True,
            text=True
        )
        if test_proc.returncode != 0:
            print(f"[!] Tests failed: {test_proc.stderr}")
    
    # Find binary (project-specific, may need adjustment)
    binary_path = None
    src_dir = Path(project_path) / "src"
    if src_dir.exists():
        # Look for executable files
        for item in src_dir.iterdir():
            if item.is_file() and os.access(item, os.X_OK):
                binary_path = str(item)
                break
    
    return CompilationResult(
        success=True,
        binary_path=binary_path,
        error_message=None,
        compilation_time=0.0,
        coverage_enabled=True,
        build_system=BuildSystem.MAKE
    )


def _compile_cmake(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool
) -> CompilationResult:
    """Compile CMake-based project."""
    flag = "1" if enabled else "0"
    target = f"-DCONFIG_{feature.upper()}={flag}"
    
    build_dir = Path(project_path) / "build"
    build_dir.mkdir(exist_ok=True)
    
    # Configure with CMake
    cmake_proc = subprocess.run(
        ["cmake", target, "-DCMAKE_BUILD_TYPE=Debug", 
         "-DCMAKE_C_FLAGS=--coverage", "-DCMAKE_CXX_FLAGS=--coverage", ".."],
        cwd=build_dir,
        capture_output=True,
        text=True
    )
    
    if cmake_proc.returncode != 0:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"CMake configuration failed: {cmake_proc.stderr}",
            compilation_time=0.0,
            coverage_enabled=True,
            build_system=BuildSystem.CMAKE
        )
    
    # Build
    make_proc = subprocess.run(
        ["make", "-j3"],
        cwd=build_dir,
        capture_output=True,
        text=True
    )
    
    if make_proc.returncode != 0:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"CMake build failed: {make_proc.stderr}",
            compilation_time=0.0,
            coverage_enabled=True,
            build_system=BuildSystem.CMAKE
        )
    
    # Run tests if requested
    if run_tests:
        test_proc = subprocess.run(
            ["ctest", "--output-on-failure"],
            cwd=build_dir,
            capture_output=True,
            text=True
        )
        if test_proc.returncode != 0:
            print(f"[!] Tests failed: {test_proc.stderr}")
    
    return CompilationResult(
        success=True,
        binary_path=str(build_dir),
        error_message=None,
        compilation_time=0.0,
        coverage_enabled=True,
        build_system=BuildSystem.CMAKE
    )


def _compile_autotools(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool
) -> CompilationResult:
    """Compile Autotools-based project (e.g., FFmpeg)."""
    # Configure
    if enabled:
        configure_args = ["bash", "configure", "--toolchain=gcov"]
    else:
        configure_args = ["bash", "configure", "--toolchain=gcov", 
                         f"--disable-{feature.lower()}"]
    
    configure_proc = subprocess.run(
        configure_args,
        cwd=project_path,
        capture_output=True,
        text=True
    )
    
    if configure_proc.returncode != 0:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"Configure failed: {configure_proc.stderr}",
            compilation_time=0.0,
            coverage_enabled=True,
            build_system=BuildSystem.AUTOTOOLS
        )
    
    # Clean
    clean_proc = subprocess.run(
        ["make", "clean"],
        cwd=project_path,
        capture_output=True,
        text=True
    )
    
    # Build
    make_proc = subprocess.run(
        ["make", "-j3"],
        cwd=project_path,
        capture_output=True,
        text=True
    )
    
    if make_proc.returncode != 0:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"Make failed: {make_proc.stderr}",
            compilation_time=0.0,
            coverage_enabled=True,
            build_system=BuildSystem.AUTOTOOLS
        )
    
    # Run tests if requested
    if run_tests:
        test_proc = subprocess.run(
            ["make", "fate", "-j3", "SAMPLES=fate-suite/"],
            cwd=project_path,
            capture_output=True,
            text=True
        )
        if test_proc.returncode != 0:
            print(f"[!] Tests failed: {test_proc.stderr}")
    
    return CompilationResult(
        success=True,
        binary_path=project_path,
        error_message=None,
        compilation_time=0.0,
        coverage_enabled=True,
        build_system=BuildSystem.AUTOTOOLS
    )


def _compile_cargo(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool
) -> CompilationResult:
    """Compile Cargo-based Rust project."""
    # Set environment variables for coverage
    env = os.environ.copy()
    env["CARGO_INCREMENTAL"] = "0"
    env["RUSTFLAGS"] = "-Zprofile -Ccodegen-units=1 -Copt-level=0 -Clink-dead-code -Coverflow-checks=off -Zpanic_abort_tests -Cpanic=abort"
    env["RUSTDOCFLAGS"] = "-Cpanic=abort"
    
    # Clean
    clean_proc = subprocess.run(
        ["cargo", "clean"],
        cwd=project_path,
        capture_output=True,
        text=True,
        env=env
    )
    
    # Build
    if enabled:
        build_args = ["cargo", "build", "--features", feature.lower()]
    else:
        build_args = ["cargo", "build", "--no-default-features"]
    
    build_proc = subprocess.run(
        build_args,
        cwd=project_path,
        capture_output=True,
        text=True,
        env=env
    )
    
    if build_proc.returncode != 0:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"Cargo build failed: {build_proc.stderr}",
            compilation_time=0.0,
            coverage_enabled=True,
            build_system=BuildSystem.CARGO
        )
    
    # Run tests if requested
    if run_tests:
        test_proc = subprocess.run(
            ["cargo", "test"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env=env
        )
        if test_proc.returncode != 0:
            print(f"[!] Tests failed: {test_proc.stderr}")
    
    binary_path = str(Path(project_path) / "target" / "debug")
    
    return CompilationResult(
        success=True,
        binary_path=binary_path,
        error_message=None,
        compilation_time=0.0,
        coverage_enabled=True,
        build_system=BuildSystem.CARGO
    )


def compile_with_adapter(
    adapter,
    feature: str,
    enabled: bool,
    run_tests: bool = False
) -> CompilationResult:
    """
    Compile a project using a ProjectAdapter.

    This is the preferred compilation path when an adapter is available.
    The adapter provides project-specific commands, flags, and paths
    instead of using the generic build-system dispatch.

    Args:
        adapter: A ProjectAdapter instance for the target project
        feature: Feature name to enable/disable
        enabled: True for feature enabled, False for disabled
        run_tests: Whether to run test suite after compilation

    Returns:
        CompilationResult with status, binary path, and error messages
    """
    start_time = time.time()

    try:
        project_path = str(adapter.project_path)
        env = os.environ.copy()
        env.update(adapter.get_coverage_environment())

        # Step 1: Clean
        clean_cmd = adapter.get_clean_command()
        subprocess.run(
            clean_cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            env=env,
        )

        # Step 2: Compile
        compile_cmd = adapter.get_compile_command(feature, enabled, with_coverage=True)
        compile_proc = subprocess.run(
            compile_cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            env=env,
        )

        if compile_proc.returncode != 0:
            return CompilationResult(
                success=False,
                binary_path=None,
                error_message=f"Compilation failed: {compile_proc.stderr}",
                compilation_time=time.time() - start_time,
                coverage_enabled=True,
                build_system=adapter.build_system,
            )

        # Step 3: Tests (optional)
        if run_tests:
            test_cmd = adapter.get_test_command()
            if test_cmd:
                test_proc = subprocess.run(
                    test_cmd,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if test_proc.returncode != 0:
                    print(f"[!] Tests failed: {test_proc.stderr}")

        return CompilationResult(
            success=True,
            binary_path=adapter.get_binary_path(),
            error_message=None,
            compilation_time=time.time() - start_time,
            coverage_enabled=True,
            build_system=adapter.build_system,
        )

    except Exception as e:
        return CompilationResult(
            success=False,
            binary_path=None,
            error_message=f"Compilation with adapter failed: {e}",
            compilation_time=time.time() - start_time,
            coverage_enabled=False,
            build_system=adapter.build_system,
        )
