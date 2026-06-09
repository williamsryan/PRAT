"""
Symbolic test case generation module for PRAT.

Paper §5.3–5.4: Uses KLEE symbolic execution engine to generate
high-coverage test cases. KLEE explores program paths symbolically,
generating concrete inputs that traverse new paths. These tests are
then replayed against the real binary during coverage analysis.

Pipeline:
1. Compile source to LLVM bytecode (clang → .bc)
2. Run KLEE on bytecode with configured parameters
3. Collect generated test cases from klee-out/
4. Replay tests against actual binary via klee-replay

KLEE requires a specific environment (LLVM 9/11, uclibc, etc.).
This module supports both local KLEE and Docker-based execution.
"""

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class KleeConfig:
    """Configuration for KLEE symbolic execution.

    Paper Table 2: General parameters for test case generation.
    """
    libc: str = "uclibc"
    runtime: str = "posix-runtime"
    sym_args: str = "0 3 4"       # symbolic argument range
    sym_files: str = "2 4"         # num symbolic files, size
    max_fail: int = 1
    max_time: int = 60             # seconds per KLEE run
    solver_backend: str = "z3"
    emit_all_errors: bool = True
    only_output_states_covering_new: bool = True
    extra_flags: list[str] = field(default_factory=list)
    link_libraries: list[str] = field(default_factory=list)

    def to_klee_args(self) -> list[str]:
        """Convert config to KLEE command-line arguments."""
        args = []
        if self.emit_all_errors:
            args.append("-emit-all-errors")
        if self.only_output_states_covering_new:
            args.append("-only-output-states-covering-new")
        args.extend(["--libc", self.libc])
        args.append(f"--{self.runtime}")
        args.extend(["--solver-backend", self.solver_backend])
        args.extend(["--max-time", str(self.max_time)])
        args.extend(["--max-fail", str(self.max_fail)])

        for lib in self.link_libraries:
            args.extend(["-link-llvm-lib", lib])

        args.extend(self.extra_flags)
        return args

    def to_replay_sym_args(self) -> list[str]:
        """Get --sym-args and --sym-files as replay-compatible args."""
        parts = self.sym_args.split()
        args = ["--sym-args"] + parts
        fparts = self.sym_files.split()
        args += ["--sym-files"] + fparts
        return args


@dataclass
class SymbolicResult:
    """Result of symbolic test generation."""
    success: bool
    test_cases: list[str]           # paths to .ktest files
    test_count: int
    bytecode_path: Optional[str] = None
    klee_output_dir: Optional[str] = None
    generation_time: float = 0.0
    replay_results: Optional[dict[str, bool]] = None
    error_message: Optional[str] = None


def check_klee_available(use_docker: bool = False) -> bool:
    """Check if KLEE is available locally or via Docker."""
    if use_docker:
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", "klee/klee:latest"],
                capture_output=True, text=True, timeout=10,
            )
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    else:
        return shutil.which("klee") is not None


def compile_to_bytecode(
    source_files: list[str],
    output_path: str,
    include_dirs: Optional[list[str]] = None,
    clang_binary: str = "clang",
    extra_flags: Optional[list[str]] = None,
) -> Optional[str]:
    """
    Compile C/C++ source files to LLVM bytecode (.bc).

    Paper §5.3 step 1: Compile source code to LLVM bytecode.

    Args:
        source_files: List of .c/.cpp source files
        output_path: Output .bc file path
        include_dirs: Additional include directories
        clang_binary: Path to clang (default: system clang)
        extra_flags: Additional compilation flags

    Returns:
        Path to .bc file, or None on failure
    """
    cmd = [clang_binary, "-emit-llvm", "-c", "-g", "-O0"]

    if include_dirs:
        for inc in include_dirs:
            cmd.extend(["-I", inc])

    if extra_flags:
        cmd.extend(extra_flags)

    cmd.extend(source_files)
    cmd.extend(["-o", output_path])

    print(f"[+] Compiling to LLVM bytecode: {' '.join(cmd[:5])}...")

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            print(f"[!] Bytecode compilation failed: {proc.stderr[:500]}")
            return None

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"[+] Bytecode generated: {output_path} ({size} bytes)")
            return output_path
        else:
            print("[!] Bytecode file not created")
            return None

    except subprocess.TimeoutExpired:
        print("[!] Bytecode compilation timed out")
        return None
    except FileNotFoundError:
        print(f"[!] clang not found at: {clang_binary}")
        return None


def run_klee(
    bytecode_path: str,
    config: Optional[KleeConfig] = None,
    output_dir: Optional[str] = None,
    use_docker: bool = False,
    docker_image: str = "klee/klee:latest",
) -> SymbolicResult:
    """
    Run KLEE symbolic execution on LLVM bytecode.

    Paper §5.3 step 2: Run KLEE on the bytecode with configured
    parameters. When KLEE explores a new path, it generates a test
    case with the concrete inputs needed to traverse that path.

    Args:
        bytecode_path: Path to .bc file
        config: KLEE configuration. Defaults are inspired by the paper's
            Table 2 and may need target-specific tuning.
        output_dir: Directory for KLEE output (auto-generated if None)
        use_docker: Run KLEE inside Docker container
        docker_image: Docker image to use for KLEE

    Returns:
        SymbolicResult with generated test cases
    """
    if config is None:
        config = KleeConfig()

    start_time = time.time()

    if output_dir is None:
        output_dir = str(Path(bytecode_path).parent / "klee-out")

    print(f"[+] Running KLEE on {bytecode_path}")
    print(f"    Config: max_time={config.max_time}s, solver={config.solver_backend}")

    try:
        if use_docker:
            result = _run_klee_docker(bytecode_path, config, output_dir, docker_image)
        else:
            result = _run_klee_local(bytecode_path, config, output_dir)

        generation_time = time.time() - start_time
        result.generation_time = generation_time

        if result.success:
            print(f"[+] KLEE generated {result.test_count} test cases "
                  f"in {generation_time:.1f}s")
        else:
            print(f"[!] KLEE failed: {result.error_message}")

        return result

    except Exception as e:
        return SymbolicResult(
            success=False,
            test_cases=[],
            test_count=0,
            generation_time=time.time() - start_time,
            error_message=f"KLEE execution failed: {e}",
        )


def _run_klee_local(
    bytecode_path: str,
    config: KleeConfig,
    output_dir: str,
) -> SymbolicResult:
    """Run KLEE locally."""
    cmd = ["klee"]
    cmd.extend(config.to_klee_args())
    cmd.extend(["--output-dir", output_dir])
    cmd.append(bytecode_path)
    cmd.extend(config.to_replay_sym_args())

    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.max_time + 30,
    )

    return _collect_klee_results(output_dir, bytecode_path, proc)


def _run_klee_docker(
    bytecode_path: str,
    config: KleeConfig,
    output_dir: str,
    docker_image: str,
) -> SymbolicResult:
    """Run KLEE inside Docker container."""
    bc_dir = str(Path(bytecode_path).parent)
    bc_name = Path(bytecode_path).name

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{bc_dir}:/work",
        "-v", f"{output_dir}:/output",
        "-w", "/work",
        docker_image,
        "klee",
    ]
    cmd.extend(config.to_klee_args())
    cmd.extend(["--output-dir", "/output"])
    cmd.append(f"/work/{bc_name}")
    cmd.extend(config.to_replay_sym_args())

    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=config.max_time + 60,
    )

    return _collect_klee_results(output_dir, bytecode_path, proc)


def _collect_klee_results(
    output_dir: str,
    bytecode_path: str,
    proc: subprocess.CompletedProcess,
) -> SymbolicResult:
    """Collect KLEE output (.ktest files)."""
    test_cases = []

    if os.path.isdir(output_dir):
        for f in sorted(os.listdir(output_dir)):
            if f.endswith(".ktest"):
                test_cases.append(os.path.join(output_dir, f))

    return SymbolicResult(
        success=len(test_cases) > 0 or proc.returncode == 0,
        test_cases=test_cases,
        test_count=len(test_cases),
        bytecode_path=bytecode_path,
        klee_output_dir=output_dir,
    )


def replay_tests(
    binary_path: str,
    test_cases: list[str],
    timeout_per_test: int = 10,
    klee_replay_binary: str = "klee-replay",
) -> dict[str, bool]:
    """
    Replay KLEE-generated test cases against the actual binary.

    Paper §5.3: "KLEE-generated tests can be replayed against the
    actual protocol binary by using the klee-replay utility."

    This generates .gcda coverage data from each test execution.

    Args:
        binary_path: Path to the compiled (coverage-instrumented) binary
        test_cases: List of .ktest file paths
        timeout_per_test: Seconds per test replay
        klee_replay_binary: Path to klee-replay

    Returns:
        Dict mapping test file → True (pass) / False (crash/timeout)
    """
    if not shutil.which(klee_replay_binary):
        print(f"[!] {klee_replay_binary} not found — cannot replay tests")
        return {}

    print(f"[+] Replaying {len(test_cases)} KLEE test cases against {binary_path}")
    results = {}

    for ktest in test_cases:
        name = Path(ktest).name
        try:
            env = os.environ.copy()
            env["KTEST_FILE"] = ktest

            proc = subprocess.run(
                [klee_replay_binary, binary_path, ktest],
                capture_output=True, text=True,
                timeout=timeout_per_test, env=env,
            )
            results[name] = (proc.returncode == 0)

        except subprocess.TimeoutExpired:
            results[name] = True  # Timeout OK — still generates coverage
        except Exception as e:
            results[name] = False
            print(f"    [!] {name}: replay error: {e}")

    passed = sum(1 for v in results.values() if v)
    print(f"[+] Replay complete: {passed}/{len(results)} passed")
    return results


def generate_symbolic_tests(
    project_path: str,
    source_files: Optional[list[str]] = None,
    binary_path: Optional[str] = None,
    config: Optional[KleeConfig] = None,
    output_dir: Optional[str] = None,
    use_docker: bool = False,
    replay: bool = True,
) -> SymbolicResult:
    """
    End-to-end symbolic test generation pipeline.

    Orchestrates: compile → KLEE → (optional) replay.

    Args:
        project_path: Path to project root
        source_files: Source files to compile (auto-detected if None)
        binary_path: Path to compiled binary for replay
        config: KLEE configuration
        output_dir: Output directory
        use_docker: Use Docker for KLEE execution
        replay: Whether to replay generated tests

    Returns:
        SymbolicResult with test cases and replay results
    """
    project = Path(project_path)

    if output_dir is None:
        output_dir = str(project / "klee_output")
    os.makedirs(output_dir, exist_ok=True)

    if config is None:
        config = KleeConfig()

    print(f"\n{'='*50}")
    print("PRAT Symbolic Test Generation")
    print(f"{'='*50}\n")

    # Step 1: Find source files if not specified
    if source_files is None:
        source_files = []
        for ext in ("*.c", "*.cpp"):
            for src_dir in ["src", "lib", "."]:
                d = project / src_dir
                if d.exists():
                    source_files.extend(str(f) for f in d.glob(ext))
        if not source_files:
            return SymbolicResult(
                success=False, test_cases=[], test_count=0,
                error_message="No source files found for bytecode compilation",
            )

    print(f"[1/3] Compiling {len(source_files)} files to LLVM bytecode...")

    # Step 2: Compile to bytecode
    bc_path = os.path.join(output_dir, "program.bc")
    bc_result = compile_to_bytecode(
        source_files, bc_path,
        include_dirs=[str(project / "src"), str(project / "lib")],
    )

    if bc_result is None:
        return SymbolicResult(
            success=False, test_cases=[], test_count=0,
            error_message="Bytecode compilation failed",
        )

    # Step 3: Run KLEE
    print(f"\n[2/3] Running KLEE symbolic execution (max {config.max_time}s)...")
    klee_out = os.path.join(output_dir, "klee-out")
    result = run_klee(bc_path, config, klee_out, use_docker)

    if not result.success:
        return result

    # Step 4: Replay (optional)
    if replay and binary_path and result.test_cases:
        print(f"\n[3/3] Replaying {result.test_count} tests against binary...")
        result.replay_results = replay_tests(binary_path, result.test_cases)
    else:
        print(f"\n[3/3] Skipping replay (binary={'available' if binary_path else 'none'}, "
              f"tests={result.test_count})")

    return result
