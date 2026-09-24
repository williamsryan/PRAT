#!/usr/bin/env python3
"""
Coverage generation module for PRAT.

This module handles generation and organization of gcov/llvm-cov coverage files
from compiled binaries with instrumentation.
"""


from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ProjectAdapter
from .compilation import BuildSystem
from .gcov import parse_tool_function_output, write_function_sidecar


@dataclass
class CoverageResult:
    """Result of coverage generation operation."""
    success: bool
    coverage_files: list[str]
    coverage_dir: str
    missing_files: list[str]
    error_message: str | None = None
    dynamic_execution: bool = False
    execution_commands: int = 0
    execution_succeeded: int = 0
    execution_failed: int = 0
    execution_timed_out: int = 0
    symbolic_tests_replayed: int = 0
    test_plan_id: str | None = None
    # Whether tests in T that could not run against this build were tolerated
    # (Algorithm 1 runs the same T against B_f, where f's own tests cannot
    # pass) and the messages of the tests that did fail, so the checkpoint
    # shows exactly which part of T contributed no coverage.
    test_failures_tolerated: bool = False
    execution_errors: list[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """Outcome of executing the complete test set used for coverage."""

    commands: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    symbolic_replayed: int = 0
    symbolic_failed: int = 0
    errors: list[str] = field(default_factory=list)
    # The commands that were actually attempted, in order, so the executed
    # test plan can be digested and compared across builds.
    executed: list[list[str]] = field(default_factory=list)
    # When True, a failing or timed-out test does not invalidate the run;
    # coverage is taken from whatever part of T did execute.
    failures_tolerated: bool = False

    @property
    def success(self) -> bool:
        """True when at least one execution completed and, unless failures are
        tolerated, none failed or timed out."""
        completed = self.succeeded + self.symbolic_replayed
        if completed == 0:
            return False
        if self.failures_tolerated:
            return True
        return (
            self.failed == 0
            and self.timed_out == 0
            and self.symbolic_failed == 0
        )

    def error_message(self) -> str:
        """Describe why the dynamic execution gate failed."""
        if self.commands == 0 and self.symbolic_replayed == 0:
            return "No unit or symbolic tests were executed"
        parts = []
        if self.failed:
            parts.append(f"{self.failed} command(s) failed")
        if self.timed_out:
            parts.append(f"{self.timed_out} command(s) timed out")
        if self.symbolic_failed:
            parts.append(f"{self.symbolic_failed} symbolic replay(s) failed")
        parts.extend(self.errors)
        return "; ".join(parts) or "Dynamic execution did not complete"


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

        success = len(coverage_files) > 0 and not missing_files
        error_message = None

        if not success:
            error_message = "No coverage files were generated"
        elif missing_files:
            error_message = (
                f"Coverage generation was incomplete for "
                f"{len(missing_files)} input(s)"
            )

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
    output_dir: str,
    label: str | None = None,
) -> str:
    """
    Move coverage files to organized directory structure.

    Args:
        coverage_files: List of paths to .gcov files
        feature: Feature name
        enabled: Whether feature was enabled
        output_dir: Base output directory
        label: Explicit directory label, overriding the feature/enabled pair.
            Batch analysis uses this for the shared ``all_features`` baseline.

    Returns:
        Path to coverage directory
    """
    if label:
        coverage_dir_name = f"coverage_files_{label}"
    else:
        flag = "yes" if enabled else "no"
        coverage_dir_name = f"coverage_files_WITH_{feature.upper()}_{flag}"
    coverage_dir = Path(output_dir) / coverage_dir_name

    # A rerun must not inherit files from a previous successful analysis.
    if coverage_dir.exists():
        shutil.rmtree(coverage_dir)
    coverage_dir.mkdir(parents=True, exist_ok=True)

    # Move coverage files
    moved_files = []
    for cov_file in coverage_files:
        cov_path = Path(cov_file)
        if not cov_path.exists():
            raise FileNotFoundError(f"Coverage artifact disappeared: {cov_file}")
        source_identity = _coverage_source_identity(cov_path)
        digest = hashlib.sha256(source_identity.encode()).hexdigest()[:16]
        dest = coverage_dir / f"{digest}-{cov_path.name}"
        shutil.move(str(cov_path), str(dest))
        moved_files.append(str(dest))

    print(f"[+] Organized {len(moved_files)} coverage files in {coverage_dir}")

    return str(coverage_dir)


def _coverage_source_identity(path: Path) -> str:
    """Read gcov's Source header so equal basenames cannot overwrite."""
    try:
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for _ in range(8):
                line = handle.readline()
                if not line:
                    break
                if "Source:" in line:
                    return line.split("Source:", 1)[1].strip()
    except OSError:
        pass
    return str(path.resolve())


def _gcov_command(coverage_tool: str, args: str) -> str:
    """Build a gcov invocation, always requesting per-function summaries.

    ``-f`` makes gcov interleave "function <name> called N ..." lines into the
    .gcov output, which is the only way to obtain the function-level coverage the
    paper reports alongside line coverage. It does not change line counts.
    """
    base = f"{coverage_tool} gcov" if "llvm-cov" in coverage_tool else coverage_tool
    return f"{base} -f {args}"


def _coverage_inputs(directory: Path) -> str:
    """Choose coverage artifacts instead of passing every directory entry."""
    return "*.gcda" if any(directory.glob("*.gcda")) else "*.gcno"


def _detect_coverage_tool() -> str:
    """Detect which coverage tool is available."""
    if shutil.which("gcov"):
        return "gcov"
    # Prefer an unversioned llvm-cov, then fall back to versioned names for
    # distributions that only ship those.
    for candidate in ("llvm-cov", "llvm-cov-18", "llvm-cov-15", "llvm-cov-14",
                      "llvm-cov-11", "llvm-cov-9"):
        if shutil.which(candidate):
            return candidate
    raise RuntimeError("No coverage tool found (gcov or llvm-cov)")


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

        for stale in directory.glob("*.gcov"):
            stale.unlink()

        # Run coverage tool
        cmd = _gcov_command(coverage_tool, _coverage_inputs(directory))

        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=directory,
            capture_output=True,
            text=True
        )
        if proc.returncode != 0:
            missing_files.append(
                f"{directory}: {proc.stderr or proc.stdout or 'gcov failed'}"
            )
            continue

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
    """Collect dynamic coverage for CMake-based projects.

    The adapter path executes and gates the test workload before this collector
    runs. gcov is invoked from every directory containing a ``.gcno`` graph so
    it can consume the sibling ``.gcda`` profiles generated by that workload.
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
        for stale in parent_dir.glob("*.gcov"):
            stale.unlink()
        cmd = _gcov_command(coverage_tool, "*.gcno")

        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=parent_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            missing_files.extend(str(path) for path in parent_dir.glob("*.gcno"))
            continue

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
        cmd = _gcov_command(coverage_tool, f"{lib_dir}/*")

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
    count 0 are written as never-executed (``#####``), and executed lines carry
    their run count. The normal gcov parser then builds the executed-line sets
    used by the same ``L_all \\ L_f`` mapping as C/C++ projects.
    """
    os.makedirs(out_dir, exist_ok=True)
    files: list[str] = []
    cur_sf: str | None = None
    da: list[tuple[int, int]] = []

    def flush() -> None:
        nonlocal cur_sf, da
        if cur_sf and da:
            digest = hashlib.sha256(cur_sf.encode()).hexdigest()[:16]
            gcov_path = os.path.join(
                out_dir, f"{digest}-{os.path.basename(cur_sf)}.gcov"
            )
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
    symbolic_tests: list[str] | None = None,
    binary_path: str | None = None,
    execution_commands: list[list[str]] | None = None,
    allow_failures: bool = False,
) -> ExecutionResult:
    """
    Execute the test suite T to generate .gcda profile data.

    Algorithm 1 line 3 defines T = U u S: the unit tests U shipped with the
    project, plus the set S generated by symbolic execution. Both are run here,
    against the *same* instrumented build, because coverage is only dynamic once
    the binary has actually executed — compilation alone produces .gcno but no
    .gcda, and gcov needs both.

    Args:
        adapter: A ProjectAdapter instance.
        feature: Feature name being analyzed.
        enabled: Whether the feature is enabled in this build.
        timeout: Max seconds per execution command.
        symbolic_tests: Paths to KLEE ``.ktest`` files (the set S), replayed via
            klee-replay against ``binary_path``.
        binary_path: Instrumented binary to replay symbolic tests against.
        execution_commands: The fixed plan U to run, unchanged, against this
            build. Defaults to the adapter's polarity-specific workload.
        allow_failures: Tolerate tests that fail or time out. Algorithm 1 runs
            the same T against B_f, where the tests exercising f cannot pass;
            their failure is recorded and coverage is taken from the rest of T.
            The baseline B_all must never use this.

    Returns:
        Structured result. Coverage is valid only when at least one test or
        symbolic replay completes successfully and, unless ``allow_failures``
        is set, none fail or time out.
    """
    project_path = str(adapter.project_path)
    env = os.environ.copy()
    env.update(adapter.get_coverage_environment())

    result = ExecutionResult(failures_tolerated=allow_failures)

    # --- U: unit tests shipped with the project -----------------------------
    exec_cmds = (
        execution_commands
        if execution_commands is not None
        else adapter.get_execution_commands(feature, enabled)
    )
    if not exec_cmds:
        print("    [!] Adapter provided no execution commands (U is empty)")
    for cmd in exec_cmds:
        result.commands += 1
        result.executed.append(list(cmd))
        try:
            print(f"    Running: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
            if proc.returncode == 0:
                result.succeeded += 1
            else:
                result.failed += 1
                detail = (proc.stderr or proc.stdout or "").strip().splitlines()
                message = detail[-1] if detail else f"exit code {proc.returncode}"
                result.errors.append(f"{' '.join(cmd)}: {message}")
                if allow_failures:
                    print("    [!] Test failed in this build; tolerated "
                          "(contributes no coverage)")
        except subprocess.TimeoutExpired:
            print(f"    [!] Execution timed out after {timeout}s")
            result.timed_out += 1
            result.errors.append(f"{' '.join(cmd)}: timed out after {timeout}s")
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"    [!] Execution failed: {exc}")
            result.failed += 1
            result.errors.append(f"{' '.join(cmd)}: {exc}")

    # --- S: symbolically generated tests ------------------------------------
    if symbolic_tests:
        if binary_path is None:
            binary_path = adapter.get_binary_path()

        if binary_path and Path(binary_path).is_file():
            from .symbolic import replay_tests

            print(f"    Replaying {len(symbolic_tests)} symbolic test(s) "
                  f"against {binary_path}")
            replayed = replay_tests(binary_path, symbolic_tests)
            if replayed:
                result.symbolic_replayed += sum(replayed.values())
                result.symbolic_failed += sum(not value for value in replayed.values())
        else:
            print("    [!] No instrumented binary available — cannot replay "
                  "symbolic tests (S excluded from T)")
            result.symbolic_failed += len(symbolic_tests)

    if not result.success:
        print(f"    [!] Dynamic execution invalid: {result.error_message()}")

    return result


def generate_coverage_with_adapter(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
    output_dir: str | None = None,
    symbolic_tests: list[str] | None = None,
    feature_states: dict[str, bool] | None = None,
    label: str | None = None,
    execution_commands: list[list[str]] | None = None,
    test_plan_id: str | None = None,
    allow_test_failures: bool = False,
) -> CoverageResult:
    """
    Generate coverage files using a ProjectAdapter.

    The adapter provides the coverage tool and source directories,
    replacing the hardcoded per-build-system dispatch.

    Args:
        adapter: A ProjectAdapter instance
        feature: Feature name
        enabled: Whether feature was enabled during compilation
        output_dir: Base directory for organized coverage output
        symbolic_tests: KLEE ``.ktest`` paths forming the set S of T = U u S
        feature_states: Explicit state for every feature, for the Algorithm 1
            baselines. Used by Cargo projects, whose coverage command carries
            the feature list.
        label: Directory label for the organized output. Defaults to the
            ``feature``/``enabled`` pair; batch analysis passes an explicit
            label such as ``all_features``.
        execution_commands: A precomputed test plan to execute unchanged.
        test_plan_id: Digest identifying that test plan across builds. When
            this function runs the plan itself, the recorded digest is
            recomputed from the commands actually executed, so a build that
            ran a different plan cannot inherit the caller's digest.
        allow_test_failures: Tolerate tests in T that cannot pass against this
            build (a B_f build lacking f). Never set for B_all.

    Returns:
        CoverageResult with paths to generated .gcov files
    """
    coverage_tool = adapter.coverage_tool
    source_dirs = adapter.source_directories
    project_path = Path(str(adapter.project_path))

    coverage_files: list[str] = []
    missing_files: list[str] = []
    # gcov stdout, kept so per-function summaries survive on tools that print
    # them rather than writing them into the .gcov files.
    tool_output: list[str] = []

    try:
        # Step 1: Execute binary/tests to generate .gcda profile data
        # This is what makes coverage DYNAMIC (paper §5.2)
        print("    Executing test suite T for dynamic coverage...")
        coverage_runs_tests = adapter.coverage_command_executes_tests() is True
        execution = ExecutionResult()
        if not coverage_runs_tests:
            execution = execute_for_coverage(
                adapter,
                feature,
                enabled,
                symbolic_tests=symbolic_tests,
                execution_commands=execution_commands,
                allow_failures=allow_test_failures,
            )
            # The digest of record is what ran, not what was requested.
            test_plan_id = test_plan_digest(execution.executed, symbolic_tests)
            if not execution.success:
                return CoverageResult(
                    success=False,
                    coverage_files=[],
                    coverage_dir="",
                    missing_files=[],
                    error_message=execution.error_message(),
                    dynamic_execution=False,
                    execution_commands=execution.commands,
                    execution_succeeded=execution.succeeded,
                    execution_failed=execution.failed,
                    execution_timed_out=execution.timed_out,
                    symbolic_tests_replayed=execution.symbolic_replayed,
                    test_plan_id=test_plan_id,
                    test_failures_tolerated=allow_test_failures,
                    execution_errors=list(execution.errors),
                )
            if execution.errors:
                print(f"    [+] Execution complete — {execution.succeeded} of "
                      f"{execution.commands} test command(s) ran; "
                      f"{len(execution.errors)} could not run in this build")
            else:
                print("    [+] Execution complete — .gcda profile data generated")

        # Step 2: Run coverage tool (gcov/llvm-cov) on .gcno + .gcda files.
        # CMake builds put .gcda files under build/; use the cmake path.
        # Make/Autotools builds put them alongside source files.
        if adapter.build_system in (BuildSystem.CMAKE, BuildSystem.MPC):
            coverage_files, missing_files = _generate_coverage_cmake(
                str(project_path),
                coverage_tool,
                getattr(adapter, "cmake_build_dir", "build"),
            )
        elif adapter.build_system == BuildSystem.CARGO and hasattr(adapter, "get_llvm_cov_command"):
            # Rust: source-based coverage via `cargo llvm-cov` (builds + runs lib
            # tests + emits lcov), then convert lcov -> PRAT .gcov files.
            flag = label or ("yes" if enabled else "no")
            lcov_path = str(project_path / f".prat_cov_{flag}.lcov")
            if feature_states and hasattr(adapter, "get_llvm_cov_command_for_set"):
                llvm_cmd = adapter.get_llvm_cov_command_for_set(
                    feature_states, lcov_path
                )
            else:
                llvm_cmd = adapter.get_llvm_cov_command(feature, enabled, lcov_path)
            print(f"    Running: {' '.join(llvm_cmd)}")
            cargo_env = os.environ.copy()
            cargo_env.update(adapter.get_coverage_environment())
            proc = subprocess.run(
                llvm_cmd, cwd=str(project_path), capture_output=True, text=True, env=cargo_env,
            )
            if proc.returncode == 0 and os.path.exists(lcov_path):
                execution.commands = 1
                execution.succeeded = 1
                tmp_gcov = project_path / f".prat_gcov_{flag}"
                coverage_files = _lcov_to_gcov(lcov_path, str(tmp_gcov))
            else:
                execution.commands = 1
                execution.failed = 1
                coverage_files = []
                detail = (proc.stderr or proc.stdout or "").strip()
                missing_files = [
                    detail[-1000:] if detail else "cargo llvm-cov produced no lcov"
                ]
        elif adapter.build_system == BuildSystem.AUTOTOOLS:
            # Autotools projects (e.g. FFmpeg) compile from the project ROOT, so
            # each .gcno records its source path relative to the root
            # (e.g. "libavcodec/libx264.c"). gcov must therefore be invoked FROM
            # the root, or it cannot locate the source and emits an empty
            # header-only .gcov. Run gcov on the .gcno graphs per source dir,
            # from the project root, and collect the .gcov files produced there.
            seen: set[str] = set()
            for stale in project_path.glob("*.gcov"):
                stale.unlink()
            for src_dir_name in source_dirs:
                src_dir = project_path / src_dir_name
                if not src_dir.exists():
                    continue
                proc = subprocess.run(
                    _gcov_command(coverage_tool, f"{src_dir_name}/*.gcno"),
                    shell=True,
                    cwd=str(project_path),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    missing_files.append(
                        f"{src_dir_name}: "
                        f"{proc.stderr or proc.stdout or 'gcov failed'}"
                    )
                    continue
                if isinstance(proc.stdout, str):
                    tool_output.append(proc.stdout)
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

                for stale in src_dir.glob("*.gcov"):
                    stale.unlink()
                cmd = _gcov_command(coverage_tool, _coverage_inputs(src_dir))

                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=src_dir,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    missing_files.append(
                        f"{src_dir_name}: "
                        f"{proc.stderr or proc.stdout or 'gcov failed'}"
                    )
                    continue
                if isinstance(proc.stdout, str):
                    tool_output.append(proc.stdout)

                for item in src_dir.iterdir():
                    if item.suffix == ".gcov":
                        coverage_files.append(str(item))

        # Adapters such as Rust execute U inside their coverage command. S still
        # has to be replayed against the same instrumented build.
        if coverage_runs_tests and symbolic_tests and execution.success:
            symbolic_execution = execute_for_coverage(
                adapter,
                feature,
                enabled,
                symbolic_tests=symbolic_tests,
                binary_path=adapter.get_binary_path(),
            )
            execution.commands += symbolic_execution.commands
            execution.succeeded += symbolic_execution.succeeded
            execution.failed += symbolic_execution.failed
            execution.timed_out += symbolic_execution.timed_out
            execution.symbolic_replayed += symbolic_execution.symbolic_replayed
            execution.symbolic_failed += symbolic_execution.symbolic_failed
            execution.errors.extend(symbolic_execution.errors)

        # Organize into standard directory structure
        base_dir = output_dir if output_dir else str(Path.cwd())
        coverage_dir = organize_coverage_files(
            coverage_files, feature, enabled, base_dir, label=label
        )
        staged_files = sorted(
            str(path) for path in Path(coverage_dir).glob("*.gcov")
        )

        if tool_output and coverage_dir:
            functions = parse_tool_function_output("\n".join(tool_output))
            if functions:
                write_function_sidecar(coverage_dir, functions)

        return CoverageResult(
            success=(
                len(staged_files) == len(coverage_files) > 0
                and execution.success
                and not missing_files
            ),
            coverage_files=staged_files,
            coverage_dir=coverage_dir,
            missing_files=missing_files,
            error_message=(
                None
                if (
                    len(staged_files) == len(coverage_files) > 0
                    and execution.success
                    and not missing_files
                )
                else execution.error_message()
                if not execution.success
                else f"Coverage generation was incomplete for "
                f"{len(missing_files)} input(s)"
                if missing_files
                else "No coverage files generated"
            ),
            dynamic_execution=execution.success,
            execution_commands=execution.commands,
            execution_succeeded=execution.succeeded,
            execution_failed=execution.failed,
            execution_timed_out=execution.timed_out,
            symbolic_tests_replayed=execution.symbolic_replayed,
            test_plan_id=test_plan_id,
            test_failures_tolerated=allow_test_failures,
            execution_errors=list(execution.errors),
        )

    except Exception as e:
        return CoverageResult(
            success=False,
            coverage_files=[],
            coverage_dir="",
            missing_files=[],
            error_message=f"Coverage generation with adapter failed: {e}",
            test_plan_id=test_plan_id,
            test_failures_tolerated=allow_test_failures,
        )


def test_plan_digest(
    commands: list[list[str]],
    symbolic_tests: list[str] | None = None,
) -> str:
    """Hash the immutable workload definition used across differential builds."""
    symbolic = []
    for test in sorted(symbolic_tests or []):
        path = Path(test)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        symbolic.append({"name": path.name, "sha256": digest})
    payload = {"commands": commands, "symbolic_tests": symbolic}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
