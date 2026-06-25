"""
Post-removal correctness verification module for PRAT.

Paper §8.7: After feature removal, verify the debloated binary still
functions correctly by replaying available test suites.

This module runs:
1. Project's built-in unit/integration tests
2. KLEE-generated symbolic tests (if available)
3. Basic compilation sanity check

No fuzzing — just deterministic test replay.
"""

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .symbolic import SymbolicResult, replay_tests


@dataclass
class SuiteResult:
    """Result of running a single test suite."""
    name: str
    success: bool
    tests_run: int
    tests_passed: int
    tests_failed: int
    execution_time: float
    output: str = ""
    error_message: Optional[str] = None


@dataclass
class VerificationResult:
    """Result of complete post-removal verification."""
    success: bool
    compiles: bool
    test_suites: list[SuiteResult] = field(default_factory=list)
    total_tests_run: int = 0
    total_tests_passed: int = 0
    total_tests_failed: int = 0
    klee_replay_results: Optional[dict[str, bool]] = None
    total_time: float = 0.0
    error_message: Optional[str] = None

    @property
    def pass_rate(self) -> float:
        if self.total_tests_run == 0:
            return 0.0
        return self.total_tests_passed / self.total_tests_run * 100


def verify_correctness(
    project_path: str,
    adapter: Optional[Any] = None,
    build_command: Optional[list[str]] = None,
    test_commands: Optional[list[list[str]]] = None,
    symbolic_result: Optional[SymbolicResult] = None,
    binary_path: Optional[str] = None,
    timeout: int = 600,
) -> VerificationResult:
    """
    Verify a debloated project still works correctly.

    Runs available tests against the modified project:
    1. Rebuild to confirm compilation
    2. Run project test suites
    3. Replay KLEE-generated tests (if available)

    Args:
        project_path: Path to the (modified) project root
        adapter: ProjectAdapter for test commands (optional)
        build_command: Override rebuild command
        test_commands: Override test commands (list of command lists)
        symbolic_result: KLEE results with .ktest files to replay
        binary_path: Path to binary for KLEE replay
        timeout: Max seconds per test suite

    Returns:
        VerificationResult with pass/fail details
    """
    start_time = time.time()
    Path(project_path)

    print(f"\n{'='*50}")
    print("PRAT Post-Removal Verification")
    print(f"{'='*50}\n")

    result = VerificationResult(success=False, compiles=False)

    # --- Step 1: Rebuild ---
    print("[1] Rebuilding debloated project...")
    compiles = _rebuild(project_path, build_command, adapter)
    result.compiles = compiles

    if not compiles:
        result.error_message = "Debloated project failed to compile"
        result.total_time = time.time() - start_time
        print("    [✗] Compilation FAILED — verification aborted\n")
        return result

    print("    [✓] Compilation successful\n")

    # --- Step 2: Run project test suites ---
    print("[2] Running project test suites...")
    suites = _discover_test_commands(project_path, adapter, test_commands)

    if not suites:
        print("    No test suites found — skipping\n")
    else:
        print(f"    Found {len(suites)} test suite(s)\n")

    for suite_name, cmd in suites:
        print(f"    Running: {suite_name}")
        suite_result = _run_test_suite(suite_name, cmd, project_path, timeout)
        result.test_suites.append(suite_result)
        result.total_tests_run += suite_result.tests_run
        result.total_tests_passed += suite_result.tests_passed
        result.total_tests_failed += suite_result.tests_failed

        status = "✓" if suite_result.success else "✗"
        print(f"    [{status}] {suite_name}: "
              f"{suite_result.tests_passed}/{suite_result.tests_run} passed "
              f"({suite_result.execution_time:.1f}s)")

    # --- Step 3: Replay KLEE tests ---
    if symbolic_result and symbolic_result.test_cases and binary_path:
        print(f"\n[3] Replaying {symbolic_result.test_count} KLEE-generated tests...")
        replay_results = replay_tests(binary_path, symbolic_result.test_cases)
        result.klee_replay_results = replay_results

        passed = sum(1 for v in replay_results.values() if v)
        failed = len(replay_results) - passed
        result.total_tests_run += len(replay_results)
        result.total_tests_passed += passed
        result.total_tests_failed += failed

        status = "✓" if failed == 0 else "✗"
        print(f"    [{status}] KLEE replay: {passed}/{len(replay_results)} passed")
    else:
        print("\n[3] No KLEE tests to replay — skipping")

    # --- Summary ---
    result.total_time = time.time() - start_time
    result.success = result.compiles and result.total_tests_failed == 0

    print(f"\n{'='*50}")
    print(f"VERIFICATION {'PASSED' if result.success else 'FAILED'}")
    print(f"{'='*50}")
    print(f"  Compiles:     {'Yes' if result.compiles else 'NO'}")
    print(f"  Tests run:    {result.total_tests_run}")
    print(f"  Tests passed: {result.total_tests_passed}")
    print(f"  Tests failed: {result.total_tests_failed}")
    if result.total_tests_run > 0:
        print(f"  Pass rate:    {result.pass_rate:.1f}%")
    print(f"  Total time:   {result.total_time:.1f}s\n")

    return result


def _rebuild(
    project_path: str,
    build_command: Optional[list[str]],
    adapter: Optional[Any] = None,
) -> bool:
    """Rebuild the project to verify it still compiles."""
    if build_command is not None:
        commands = [build_command]
    elif adapter:
        commands = adapter.get_build_commands("", True, with_coverage=False)
    else:
        project = Path(project_path)
        if (project / "Cargo.toml").exists():
            commands = [["cargo", "build"]]
        elif (project / "CMakeLists.txt").exists():
            commands = [["make", "-C", "build", "-j"]]
        elif (project / "Makefile").exists():
            commands = [["make", "-j"]]
        else:
            return False

    try:
        for cmd in commands:
            proc = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if proc.returncode != 0:
                return False
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _discover_test_commands(
    project_path: str,
    adapter: Optional[Any] = None,
    override: Optional[list[list[str]]] = None,
) -> list[tuple]:
    """Discover available test commands. Returns list of (name, command)."""
    if override:
        return [(f"custom-{i}", cmd) for i, cmd in enumerate(override)]

    suites = []
    project = Path(project_path)

    # Adapter-provided tests
    if adapter:
        test_cmd = adapter.get_test_command()
        if test_cmd:
            suites.append(("adapter-tests", test_cmd))

    # Common test patterns
    if (project / "Cargo.toml").exists():
        suites.append(("cargo-test", ["cargo", "test"]))
    elif (project / "Makefile").exists():
        # Check for test/check targets
        try:
            proc = subprocess.run(
                ["make", "-n", "test"],
                cwd=project_path,
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                suites.append(("make-test", ["make", "test"]))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        try:
            proc = subprocess.run(
                ["make", "-n", "check"],
                cwd=project_path,
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                suites.append(("make-check", ["make", "check"]))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # CTest
    if (project / "build").is_dir():
        suites.append(("ctest", ["ctest", "--output-on-failure"]))

    # Deduplicate by name
    seen = set()
    unique = []
    for name, cmd in suites:
        if name not in seen:
            seen.add(name)
            unique.append((name, cmd))

    return unique


def _run_test_suite(
    name: str,
    command: list[str],
    project_path: str,
    timeout: int,
) -> SuiteResult:
    """Run a single test suite and parse results."""
    start = time.time()

    try:
        proc = subprocess.run(
            command,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        elapsed = time.time() - start
        output = proc.stdout + proc.stderr

        # Try to parse test counts from output
        tests_run, tests_passed, tests_failed = _parse_test_output(output, proc.returncode)

        return SuiteResult(
            name=name,
            success=(proc.returncode == 0),
            tests_run=tests_run,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            execution_time=elapsed,
            output=output[-2000:] if len(output) > 2000 else output,
        )

    except subprocess.TimeoutExpired:
        return SuiteResult(
            name=name,
            success=False,
            tests_run=0, tests_passed=0, tests_failed=0,
            execution_time=timeout,
            error_message=f"Timed out after {timeout}s",
        )
    except Exception as e:
        return SuiteResult(
            name=name,
            success=False,
            tests_run=0, tests_passed=0, tests_failed=0,
            execution_time=time.time() - start,
            error_message=str(e),
        )


def _parse_test_output(output: str, returncode: int) -> tuple:
    """
    Best-effort parse of test counts from output.

    Handles common formats:
    - "X tests passed, Y failed"
    - "Ran X tests"
    - Cargo: "test result: ok. X passed; Y failed"
    - CTest: "X tests passed, Y tests failed"
    """
    import re

    tests_run = 0
    tests_passed = 0
    tests_failed = 0

    # Cargo format
    m = re.search(r'test result:.*?(\d+) passed.*?(\d+) failed', output)
    if m:
        tests_passed = int(m.group(1))
        tests_failed = int(m.group(2))
        tests_run = tests_passed + tests_failed
        return tests_run, tests_passed, tests_failed

    # CTest / generic format
    m = re.search(r'(\d+)\s+tests?\s+passed', output)
    if m:
        tests_passed = int(m.group(1))

    m = re.search(r'(\d+)\s+tests?\s+failed', output)
    if m:
        tests_failed = int(m.group(1))

    # "Ran X tests"
    m = re.search(r'Ran\s+(\d+)\s+tests?', output)
    if m:
        tests_run = int(m.group(1))

    if tests_run == 0:
        tests_run = tests_passed + tests_failed

    # Fallback: if we got no info, mark 1 pass/fail based on returncode
    if tests_run == 0:
        tests_run = 1
        if returncode == 0:
            tests_passed = 1
        else:
            tests_failed = 1

    return tests_run, tests_passed, tests_failed
