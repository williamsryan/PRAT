#!/usr/bin/env python3
"""
Coverage generation module for PRAT.

This module handles generation and organization of gcov/llvm-cov coverage files
from compiled binaries with instrumentation.
"""

import contextlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .adapters import ProjectAdapter
from .compilation import BuildSystem


@dataclass
class CoverageResult:
    """Result of coverage generation operation."""
    success: bool
    coverage_files: list[str]
    coverage_dir: str
    missing_files: list[str]
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

    coverage_files: list[str] = []
    missing_files: list[str] = []

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
    coverage_files: list[str],
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
) -> tuple[list[str], list[str]]:
    """Generate coverage for Make-based projects (e.g., Mosquitto)."""
    coverage_files: list[str] = []
    missing_files: list[str] = []

    # Run coverage on src and lib directories
    src_dir = Path(project_path) / "src"
    lib_dir = Path(project_path) / "lib"

    for directory in [src_dir, lib_dir]:
        if not directory.exists():
            continue

        # Run coverage tool
        cmd = "llvm-cov-9 gcov *" if coverage_tool == "llvm-cov-9" else "gcov *"

        subprocess.run(
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
    coverage_tool: str,
    build_dir_name: str = "build",
) -> tuple[list[str], list[str]]:
    """Generate coverage for CMake-based projects.

    PRAT performs *compile-time* differential coverage (README: "compiles a
    project with and without a feature flag, generates coverage data"). gcov
    produces a .gcov file from the compile-time .gcno graph alone, marking every
    instrumented line as never-executed (#####) when no runtime .gcda is
    present. That is exactly what the working Make/Autotools paths rely on.

    The previous implementation only ran gcov on .gcda files, so a CMake build
    that was compiled-but-not-executed (the common case for large libraries with
    tests disabled) produced ZERO .gcov files and the whole workflow failed.

    We therefore drive gcov from the .gcno files (the superset that always
    exists after a coverage build). gcov automatically consumes a sibling .gcda
    when present, so this still yields true dynamic coverage whenever the binary
    or test suite was executed.
    """
    coverage_files: list[str] = []
    missing_files: list[str] = []

    build_dir = Path(project_path) / build_dir_name

    if not build_dir.exists():
        return coverage_files, missing_files

    # Group instrumentation graphs by directory so we invoke gcov once per dir.
    gcno_dirs = {gcno.parent for gcno in build_dir.rglob("*.gcno")}

    seen: set[str] = set()
    for parent_dir in sorted(gcno_dirs):
        cmd = "llvm-cov-9 gcov *.gcno" if coverage_tool == "llvm-cov-9" else "gcov *.gcno"

        subprocess.run(
            cmd,
            shell=True,
            cwd=parent_dir,
            capture_output=True,
            text=True,
        )

        # Collect generated .gcov files (dedupe across iterations).
        for item in parent_dir.iterdir():
            if item.suffix == ".gcov":
                path = str(item)
                if path not in seen:
                    seen.add(path)
                    coverage_files.append(path)

    return coverage_files, missing_files


def _generate_coverage_autotools(
    project_path: str,
    coverage_tool: str
) -> tuple[list[str], list[str]]:
    """Generate coverage for Autotools-based projects (e.g., FFmpeg)."""
    coverage_files: list[str] = []
    missing_files: list[str] = []

    project = Path(project_path)

    # FFmpeg-specific directories
    lib_dirs = ["libavcodec", "libavfilter", "libavformat"]

    for lib_dir in lib_dirs:
        lib_path = project / lib_dir
        if not lib_path.exists():
            continue

        # Run coverage tool
        if coverage_tool == "llvm-cov-9":
            cmd = f"llvm-cov-9 gcov {lib_dir}/*"
        else:
            cmd = f"gcov {lib_dir}/*"

        subprocess.run(
            cmd,
            shell=True,
            cwd=project,
            capture_output=True,
            text=True
        )

        # Collect generated .gcov files from project root
        for item in project.iterdir():
            if item.suffix == ".gcov":
                coverage_files.append(str(item))

    return coverage_files, missing_files


def _lcov_to_gcov(lcov_path: str, out_dir: str) -> list[str]:
    """Convert an lcov report into PRAT-compatible per-file .gcov files.

    Rust uses source-based LLVM coverage (`cargo llvm-cov`), which emits lcov,
    not gcc .gcov. We synthesize one .gcov per source file: lines with execution
    count 0 are written as never-executed (``#####``) — exactly what PRAT's
    extraction counts as removable — and executed lines carry their run count.
    Only ``#####`` lines are parsed downstream, so this is sufficient for the
    differential.
    """
    os.makedirs(out_dir, exist_ok=True)
    files: list[str] = []
    cur_sf: Optional[str] = None
    da: list[tuple[int, int]] = []

    def flush() -> None:
        nonlocal cur_sf, da
        if cur_sf and da:
            gcov_path = os.path.join(out_dir, os.path.basename(cur_sf) + ".gcov")
            with open(gcov_path, "w", encoding="utf-8") as g:
                g.write(f"        -:    0:Source:{cur_sf}\n")
                for line, count in sorted(set(da)):
                    marker = "#####" if count == 0 else str(count)
                    g.write(f"{marker:>9}:{line:>5}:\n")
            files.append(gcov_path)
        cur_sf = None
        da = []

    with open(lcov_path, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            ln = raw.strip()
            if ln.startswith("SF:"):
                flush()
                cur_sf = ln[3:]
            elif ln.startswith("DA:"):
                parts = ln[3:].split(",")
                if len(parts) >= 2:
                    with contextlib.suppress(ValueError):
                        da.append((int(parts[0]), int(parts[1])))
            elif ln == "end_of_record":
                flush()
    flush()
    return files


def _generate_coverage_cargo(
    project_path: str,
    coverage_tool: str
) -> tuple[list[str], list[str]]:
    """Generate coverage for Cargo-based Rust projects."""
    coverage_files: list[str] = []
    missing_files: list[str] = []

    deps_dir = Path(project_path) / "target" / "debug" / "deps"

    if not deps_dir.exists():
        return coverage_files, missing_files

    # Run coverage tool
    cmd = "llvm-cov-9 gcov *" if coverage_tool == "llvm-cov-9" else "gcov-9 *"

    subprocess.run(
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


def execute_for_coverage(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
    timeout: int = 300,
) -> bool:
    """
    Execute the compiled binary / test suite to generate .gcda profile data.

    This is the critical step that makes coverage *dynamic* rather than
    compile-time only. After compilation with coverage flags, .gcno files
    exist but .gcda files are only created when the binary actually runs.
    gcov needs both .gcno and .gcda to produce accurate .gcov files.

    Args:
        adapter: A ProjectAdapter instance
        feature: Feature name being analyzed
        enabled: Whether the feature is enabled in this build
        timeout: Max seconds for execution (default 300 = 5 min)

    Returns:
        True if execution completed (even with test failures), False on error
    """
    project_path = str(adapter.project_path)
    env = os.environ.copy()
    env.update(adapter.get_coverage_environment())

    exec_cmds = adapter.get_execution_commands(feature, enabled)
    if not exec_cmds:
        print("[!] No execution commands available — coverage will be compile-time only")
        return False

    success = False
    for cmd in exec_cmds:
        try:
            print(f"    Running: {' '.join(cmd)}")
            subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
            # Test failures are OK — we still get coverage data
            success = True
        except subprocess.TimeoutExpired:
            print(f"[!] Execution timed out after {timeout}s (continuing with partial coverage)")
            success = True  # Partial coverage is still useful
        except Exception as e:
            print(f"[!] Execution failed: {e}")

    return success


def generate_coverage_with_adapter(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
    output_dir: Optional[str] = None,
) -> CoverageResult:
    """
    Generate coverage files using a ProjectAdapter.

    The adapter provides the coverage tool and source directories,
    replacing the hardcoded per-build-system dispatch.

    Args:
        adapter: A ProjectAdapter instance
        feature: Feature name
        enabled: Whether feature was enabled during compilation

    Returns:
        CoverageResult with paths to generated .gcov files
    """
    coverage_tool = adapter.coverage_tool
    source_dirs = adapter.source_directories
    project_path = Path(str(adapter.project_path))

    coverage_files: list[str] = []
    missing_files: list[str] = []

    try:
        # Step 1: Execute binary/tests to generate .gcda profile data
        # This is what makes coverage DYNAMIC (paper §5.2)
        print("    Executing tests for dynamic coverage...")
        executed = execute_for_coverage(adapter, feature, enabled)
        if executed:
            print("    [+] Execution complete — .gcda profile data generated")
        else:
            print("    [!] No execution — falling back to compile-time coverage")

        # Step 2: Run coverage tool (gcov/llvm-cov) on .gcno + .gcda files.
        # CMake builds put .gcda files under build/; use the cmake path.
        # Make/Autotools builds put them alongside source files.
        if adapter.build_system == BuildSystem.CMAKE:
            coverage_files, missing_files = _generate_coverage_cmake(
                str(project_path),
                coverage_tool,
                getattr(adapter, "cmake_build_dir", "build"),
            )
        elif adapter.build_system == BuildSystem.CARGO and hasattr(adapter, "get_llvm_cov_command"):
            # Rust: source-based coverage via `cargo llvm-cov` (builds + runs lib
            # tests + emits lcov), then convert lcov -> PRAT .gcov files.
            flag = "yes" if enabled else "no"
            lcov_path = str(project_path / f".prat_cov_{flag}.lcov")
            llvm_cmd = adapter.get_llvm_cov_command(feature, enabled, lcov_path)
            print(f"    Running: {' '.join(llvm_cmd)}")
            cargo_env = os.environ.copy()
            cargo_env.update(adapter.get_coverage_environment())
            subprocess.run(
                llvm_cmd, cwd=str(project_path), capture_output=True, text=True, env=cargo_env,
            )
            if os.path.exists(lcov_path):
                tmp_gcov = project_path / f".prat_gcov_{flag}"
                coverage_files = _lcov_to_gcov(lcov_path, str(tmp_gcov))
            else:
                coverage_files = []
                missing_files = ["cargo llvm-cov produced no lcov"]
        elif adapter.build_system == BuildSystem.AUTOTOOLS:
            # Autotools projects (e.g. FFmpeg) compile from the project ROOT, so
            # each .gcno records its source path relative to the root
            # (e.g. "libavcodec/libx264.c"). gcov must therefore be invoked FROM
            # the root, or it cannot locate the source and emits an empty
            # header-only .gcov. Run gcov on the .gcno graphs per source dir,
            # from the project root, and collect the .gcov files produced there.
            seen: set[str] = set()
            for src_dir_name in source_dirs:
                src_dir = project_path / src_dir_name
                if not src_dir.exists():
                    continue
                gcov_prog = coverage_tool if "llvm-cov" not in coverage_tool else f"{coverage_tool} gcov"
                subprocess.run(
                    f"{gcov_prog} {src_dir_name}/*.gcno",
                    shell=True,
                    cwd=str(project_path),
                    capture_output=True,
                    text=True,
                )
                for item in project_path.iterdir():
                    if item.suffix == ".gcov":
                        path = str(item)
                        if path not in seen:
                            seen.add(path)
                            coverage_files.append(path)
        else:
            for src_dir_name in source_dirs:
                src_dir = project_path / src_dir_name
                if not src_dir.exists():
                    continue

                if "llvm-cov" in coverage_tool:
                    cmd = f"{coverage_tool} gcov *"
                else:
                    cmd = f"{coverage_tool} *"

                subprocess.run(
                    cmd,
                    shell=True,
                    cwd=src_dir,
                    capture_output=True,
                    text=True,
                )

                for item in src_dir.iterdir():
                    if item.suffix == ".gcov":
                        coverage_files.append(str(item))

        # Organize into standard directory structure
        base_dir = output_dir if output_dir else str(Path.cwd())
        coverage_dir = organize_coverage_files(
            coverage_files, feature, enabled, base_dir
        )

        return CoverageResult(
            success=len(coverage_files) > 0,
            coverage_files=coverage_files,
            coverage_dir=coverage_dir,
            missing_files=missing_files,
            error_message=None if coverage_files else "No coverage files generated",
        )

    except Exception as e:
        return CoverageResult(
            success=False,
            coverage_files=[],
            coverage_dir="",
            missing_files=[],
            error_message=f"Coverage generation with adapter failed: {e}",
        )
