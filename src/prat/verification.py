"""
Post-removal correctness verification module for PRAT.

Paper, Feature Removal: "the system then re-runs the test suite, T, generated
during feature-to-code-mapping and monitors the program's output for crashes and
unexpected behavior."

Three things that phrase requires, and which this module implements:

*Re-run T, not some other suite.* T = U u S is the same fixed plan the mapping
ran against B_all and B_f (:meth:`prat.adapters.base.ProjectAdapter.get_test_plan`),
so both the project's own tests and the KLEE-generated tests are replayed when
the latter are available. Because T is fixed, it contains the tests that
exercise the removed feature f; those fail against the pre-removal B_f build
and must fail the same way against the debloated build. That is preserved
behaviour, not a regression, and is reported as an expected failure.

*Distinguish crashes from failures.* A test that exits non-zero failed; a test
killed by SIGSEGV crashed. The paper's correctness argument is about crashes, so
they are reported separately with the signal named. A crash the pre-removal
build also produced, with the same signal, is recorded as pre-existing.

*Detect unexpected behavior, not just failure.* The oracle is the pre-removal
build in the same configuration: :func:`capture_reference_outputs` records each
command's exit code and normalized output (or that it could not run), and the
post-removal run must reproduce every outcome. A test that now passes where it
failed before, fails where it passed, or prints something different, diverged.
Without a reference there is no oracle, and the result says so rather than
implying one.

Verification with no tests available is reported as ``INCONCLUSIVE``, not as a
pass: compiling is necessary but not sufficient evidence of correctness. So is
a reference in which no test passed: there is then nothing to preserve.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .symbolic import SymbolicResult, replay_tests


class VerificationStatus(Enum):
    """Outcome of verification."""

    PASSED = "passed"
    FAILED = "failed"
    CRASHED = "crashed"
    #: Compiled, but no test suite was available to exercise the result.
    INCONCLUSIVE = "inconclusive"
    #: Did not compile.
    BUILD_FAILED = "build_failed"


@dataclass
class ReferenceOutcome:
    """What one command of T did against the pre-removal build.

    The debloated build must reproduce this: same exit code, same normalized
    output, same inability to run. ``returncode`` is None when the command
    could not be started or timed out; ``error`` then says why.
    """

    returncode: int | None
    output: str
    error: str | None = None
    crash_signal: str | None = None

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    @classmethod
    def from_output(cls, output: str) -> ReferenceOutcome:
        """A passing reference known only by its output (legacy form)."""
        return cls(returncode=0, output=output)


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
    error_message: str | None = None
    #: True when the process was terminated by a signal.
    crashed: bool = False
    #: Signal name (e.g. "SIGSEGV") when ``crashed`` is True.
    crash_signal: str | None = None
    #: True when the pre-removal build crashed the same way; the crash was not
    #: introduced by removal.
    crash_preexisting: bool = False
    #: True when counts were inferred from the exit code rather than parsed.
    counts_inferred: bool = False
    #: True when the outcome diverged from the captured reference.
    output_diverged: bool = False
    #: True when the reference itself failed (a test of the removed feature);
    #: the debloated build is then required to fail the same way.
    expected_failure: bool = False
    #: The exit code recorded for the same command before removal.
    reference_returncode: int | None = None


@dataclass
class VerificationResult:
    """Result of complete post-removal verification."""

    success: bool
    compiles: bool
    status: VerificationStatus = VerificationStatus.INCONCLUSIVE
    test_suites: list[SuiteResult] = field(default_factory=list)
    total_tests_run: int = 0
    total_tests_passed: int = 0
    total_tests_failed: int = 0
    crashes: list[str] = field(default_factory=list)
    preexisting_crashes: list[str] = field(default_factory=list)
    diverged_suites: list[str] = field(default_factory=list)
    #: Commands of T that failed before removal too, and failed the same way
    #: after it. Behaviour preserved; not counted against the pass rate.
    expected_failures: list[str] = field(default_factory=list)
    klee_replay_results: dict[str, bool] | None = None
    total_time: float = 0.0
    error_message: str | None = None

    @property
    def pass_rate(self) -> float:
        if self.total_tests_run == 0:
            return 0.0
        return self.total_tests_passed / self.total_tests_run * 100

    @property
    def crashed(self) -> bool:
        return bool(self.crashes)


def capture_reference_outputs(
    project_path: str,
    adapter: Any | None = None,
    test_commands: list[list[str]] | None = None,
    timeout: int = 600,
) -> dict[str, ReferenceOutcome]:
    """Record what every command of T does against the *pre-removal* build.

    This is the oracle for "unexpected behavior": without a reference recorded
    before removal, a post-removal run can only be checked for failure, not for
    silently different behaviour. Call this before
    :func:`prat.removal.remove_feature_code` and pass the result to
    :func:`verify_correctness`.

    T is fixed (Algorithm 1 line 3), so it includes the tests of the feature
    being removed. Against the pre-removal build in the removal configuration
    those already fail, and that failure is recorded as the expected outcome
    rather than treated as an error. What is refused is a reference in which
    *nothing* passes: the debloated build would then have no behaviour to
    preserve and verification could not mean anything.
    """
    references: dict[str, ReferenceOutcome] = {}

    for name, command in _discover_test_commands(project_path, adapter, test_commands):
        try:
            proc = subprocess.run(
                command,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            references[name] = ReferenceOutcome(
                returncode=proc.returncode,
                output=_normalize_output(proc.stdout + proc.stderr),
                crash_signal=_signal_name(proc.returncode),
            )
        except subprocess.TimeoutExpired:
            references[name] = ReferenceOutcome(
                returncode=None, output="", error=f"timed out after {timeout}s"
            )
        except (OSError, subprocess.SubprocessError) as exc:
            references[name] = ReferenceOutcome(
                returncode=None, output="", error=_normalize_output(str(exc))
            )

    if references and not any(ref.passed for ref in references.values()):
        detail = "; ".join(
            f"{name}: {ref.error or f'exit code {ref.returncode}'}"
            for name, ref in references.items()
        )
        raise RuntimeError(
            "No command of T passes against the pre-removal build, so there is "
            f"no behaviour for verification to preserve ({detail})"
        )

    return references


def verify_correctness(
    project_path: str,
    adapter: Any | None = None,
    build_command: list[str] | None = None,
    build_commands: list[list[str]] | None = None,
    test_commands: list[list[str]] | None = None,
    symbolic_result: SymbolicResult | None = None,
    binary_path: str | None = None,
    reference_outputs: Mapping[str, ReferenceOutcome | str] | None = None,
    timeout: int = 600,
    require_tests: bool = True,
) -> VerificationResult:
    """
    Verify a debloated project still works correctly.

    Args:
        project_path: Path to the (modified) project root.
        adapter: ProjectAdapter supplying build/test commands and binary path.
        build_command: Override rebuild command.
        build_commands: Ordered rebuild commands for multi-step adapters.
        test_commands: The fixed test plan T (list of command lists). Falls
            back to discovering a suite when omitted.
        symbolic_result: KLEE results whose ``.ktest`` files form S of T.
        binary_path: Binary for KLEE replay; taken from ``adapter`` if omitted.
        reference_outputs: Pre-removal outcomes from
            :func:`capture_reference_outputs`, enabling divergence detection.
            A plain string value is accepted as a passing reference's output.
        timeout: Max seconds per test suite.
        require_tests: When True, a run with no discoverable tests is reported
            as INCONCLUSIVE and ``success`` is False, because compilation alone
            does not establish correctness.

    Returns:
        VerificationResult with pass/fail/crash/inconclusive details.
    """
    start_time = time.time()

    print(f"\n{'=' * 50}")
    print("PRAT Post-Removal Verification")
    print(f"{'=' * 50}\n")

    result = VerificationResult(success=False, compiles=False)

    # --- Step 1: rebuild ---------------------------------------------------
    print("[1] Rebuilding debloated project...")
    result.compiles = _rebuild(
        project_path, build_command, adapter, build_commands=build_commands
    )

    if not result.compiles:
        result.status = VerificationStatus.BUILD_FAILED
        result.error_message = "Debloated project failed to compile"
        result.total_time = time.time() - start_time
        print("    [x] Compilation FAILED — verification aborted\n")
        return result

    print("    [ok] Compilation successful\n")

    # --- Step 2: re-run U --------------------------------------------------
    print("[2] Re-running the test plan T...")
    suites = _discover_test_commands(project_path, adapter, test_commands)

    if not suites:
        print("    No test suites found\n")
    else:
        print(f"    Found {len(suites)} test command(s)\n")

    references = {
        name: (
            ReferenceOutcome.from_output(ref) if isinstance(ref, str) else ref
        )
        for name, ref in (reference_outputs or {}).items()
    }

    for suite_name, command in suites:
        print(f"    Running: {suite_name}")
        suite_result = _run_test_suite(
            suite_name,
            command,
            project_path,
            timeout,
            reference=references.get(suite_name),
        )
        result.test_suites.append(suite_result)

        if suite_result.expected_failure:
            # A test of the removed feature: it failed before removal and is
            # required to fail identically after it. Preserved behaviour, so
            # it does not count toward the pass rate either way.
            result.expected_failures.append(suite_name)
        else:
            result.total_tests_run += suite_result.tests_run
            result.total_tests_passed += suite_result.tests_passed
            result.total_tests_failed += suite_result.tests_failed

        if suite_result.crashed:
            crash = f"{suite_name}: {suite_result.crash_signal or 'terminated by signal'}"
            if suite_result.crash_preexisting:
                result.preexisting_crashes.append(crash)
            else:
                result.crashes.append(crash)
        if suite_result.output_diverged:
            result.diverged_suites.append(suite_name)

        marker = "ok" if suite_result.success else "x"
        if suite_result.expected_failure:
            detail = (
                "expected failure, behaviour preserved"
                if not suite_result.output_diverged
                else "expected failure, but behaviour CHANGED"
            )
        elif not suite_result.counts_inferred:
            detail = f"{suite_result.tests_passed}/{suite_result.tests_run} passed"
        else:
            detail = f"exit-code only ({'pass' if suite_result.success else 'fail'})"
        extra = ""
        if suite_result.crashed:
            extra += (
                f" [pre-existing crash: {suite_result.crash_signal}]"
                if suite_result.crash_preexisting
                else f" [CRASH: {suite_result.crash_signal}]"
            )
        if suite_result.output_diverged:
            extra += " [OUTCOME DIVERGED]"
        print(f"    [{marker}] {suite_name}: {detail} "
              f"({suite_result.execution_time:.1f}s){extra}")

    # --- Step 3: replay S --------------------------------------------------
    if binary_path is None and adapter is not None:
        binary_path = adapter.get_binary_path()

    if symbolic_result and symbolic_result.test_cases:
        if binary_path and os.path.exists(binary_path):
            print(f"\n[3] Replaying {symbolic_result.test_count} KLEE-generated "
                  f"test(s) against {binary_path}...")
            replay_results = replay_tests(binary_path, symbolic_result.test_cases)
            result.klee_replay_results = replay_results

            passed = sum(1 for ok in replay_results.values() if ok)
            failed = len(replay_results) - passed
            result.total_tests_run += len(replay_results)
            result.total_tests_passed += passed
            result.total_tests_failed += failed

            marker = "ok" if failed == 0 else "x"
            print(f"    [{marker}] KLEE replay: {passed}/{len(replay_results)} passed")
        else:
            print("\n[3] KLEE tests available but no binary to replay against "
                  "— verification failed")
            result.total_tests_run += len(symbolic_result.test_cases)
            result.total_tests_failed += len(symbolic_result.test_cases)
    else:
        print("\n[3] No KLEE tests to replay — skipping")

    # --- Verdict -----------------------------------------------------------
    result.total_time = time.time() - start_time
    result.status = _decide_status(result, saw_tests=bool(result.total_tests_run))
    result.success = result.status is VerificationStatus.PASSED

    if result.status is VerificationStatus.INCONCLUSIVE:
        result.error_message = (
            "Compiled, but no tests were available to exercise the debloated "
            "build; correctness is unverified"
        )
        if not require_tests:
            result.success = True

    print(f"\n{'=' * 50}")
    print(f"VERIFICATION {result.status.value.upper()}")
    print(f"{'=' * 50}")
    print(f"  Compiles:     {'Yes' if result.compiles else 'NO'}")
    print(f"  Tests run:    {result.total_tests_run}")
    print(f"  Tests passed: {result.total_tests_passed}")
    print(f"  Tests failed: {result.total_tests_failed}")
    if result.expected_failures:
        print(f"  Expected failures (tests of the removed feature, behaviour "
              f"preserved): {len(result.expected_failures)}")
    if result.crashes:
        print(f"  Crashes:      {len(result.crashes)}")
        for crash in result.crashes:
            print(f"                {crash}")
    if result.preexisting_crashes:
        print(f"  Pre-existing crashes (also before removal): "
              f"{len(result.preexisting_crashes)}")
    if result.diverged_suites:
        print(f"  Diverged:     {', '.join(result.diverged_suites)}")
    elif reference_outputs:
        print("  Diverged:     none (every outcome matched the pre-removal reference)")
    else:
        print("  Diverged:     not checked (no pre-removal reference captured)")
    if result.total_tests_run > 0:
        print(f"  Pass rate:    {result.pass_rate:.1f}%")
    print(f"  Total time:   {result.total_time:.1f}s\n")

    return result


def _decide_status(
    result: VerificationResult, saw_tests: bool
) -> VerificationStatus:
    if not result.compiles:
        return VerificationStatus.BUILD_FAILED
    if result.crashes:
        return VerificationStatus.CRASHED
    if not saw_tests:
        return VerificationStatus.INCONCLUSIVE
    if (
        result.total_tests_failed > 0
        or result.diverged_suites
        or any(not suite.success for suite in result.test_suites)
    ):
        return VerificationStatus.FAILED
    return VerificationStatus.PASSED


def _rebuild(
    project_path: str,
    build_command: list[str] | None,
    adapter: Any | None = None,
    build_commands: list[list[str]] | None = None,
) -> bool:
    """Rebuild the project to verify it still compiles."""
    if build_commands is not None:
        commands = build_commands
    elif build_command is not None:
        commands = [build_command]
    elif adapter:
        return False
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
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-10:]
                for line in tail:
                    print(f"      | {line}")
                return False
        return True
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
        return False


def _discover_test_commands(
    project_path: str,
    adapter: Any | None = None,
    override: list[list[str]] | None = None,
) -> list[tuple[str, list[str]]]:
    """Discover available test commands as ``(name, command)`` pairs."""
    if override:
        return [(f"custom-{i}", cmd) for i, cmd in enumerate(override)]

    suites: list[tuple[str, list[str]]] = []
    project = Path(project_path)

    if adapter:
        test_cmd = adapter.get_test_command()
        if test_cmd:
            suites.append(("adapter-tests", test_cmd))

    if (project / "Cargo.toml").exists():
        suites.append(("cargo-test", ["cargo", "test"]))
    elif (project / "Makefile").exists():
        for target in ("test", "check"):
            try:
                proc = subprocess.run(
                    ["make", "-n", target],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    suites.append((f"make-{target}", ["make", target]))
            except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
                pass

    if (project / "build").is_dir():
        suites.append(("ctest", ["ctest", "--output-on-failure"]))

    seen: set[str] = set()
    unique: list[tuple[str, list[str]]] = []
    for name, cmd in suites:
        if name not in seen:
            seen.add(name)
            unique.append((name, cmd))
    return unique


def _signal_name(returncode: int) -> str | None:
    """Map a process return code to a signal name, if it denotes one.

    ``subprocess`` reports signal death as a negative return code; shells
    report it as 128+signum.
    """
    signum: int | None = None
    if returncode < 0:
        signum = -returncode
    elif returncode > 128:
        signum = returncode - 128

    if signum is None:
        return None
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal {signum}"


def _normalize_output(output: str) -> str:
    """Strip content that varies run to run, so divergence means divergence.

    Removes timings, absolute paths, PIDs and addresses; without this, every
    comparison would report divergence and the oracle would be useless.
    """
    normalized = output
    normalized = re.sub(r"\b\d+\.\d+\s*(?:s|ms|sec|seconds)\b", "<time>", normalized)
    normalized = re.sub(r"0x[0-9a-fA-F]+", "<addr>", normalized)
    normalized = re.sub(r"\bpid[= ]\d+", "pid=<pid>", normalized, flags=re.I)
    normalized = re.sub(r"/[\w./+-]*/(?=[\w.+-]+\.(?:c|h|cpp|rs|py))", "", normalized)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}[ T][\d:.]+\b", "<timestamp>", normalized)
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()


def _run_test_suite(
    name: str,
    command: list[str],
    project_path: str,
    timeout: int,
    reference: ReferenceOutcome | str | None = None,
) -> SuiteResult:
    """Run one command of T, parse results, classify crashes, compare outcomes.

    With a reference, the command is required to reproduce the pre-removal
    outcome exactly: same exit code, same normalized output, or the same
    inability to run. A reference that itself failed marks the suite as an
    expected failure (a test of the removed feature); reproducing that failure
    is success, and passing instead is divergence.
    """
    start = time.time()
    if isinstance(reference, str):
        reference = ReferenceOutcome.from_output(reference)
    expected_failure = reference is not None and not reference.passed
    reference_returncode = reference.returncode if reference else None

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
        crash_signal = _signal_name(proc.returncode)

        tests_run, tests_passed, tests_failed, inferred = _parse_test_output(
            output, proc.returncode
        )

        diverged = False
        if reference is not None:
            diverged = (
                proc.returncode != reference.returncode
                or _normalize_output(output) != reference.output
            )
        crash_preexisting = (
            crash_signal is not None
            and reference is not None
            and reference.crash_signal == crash_signal
        )

        if reference is not None:
            success = not diverged and (not crash_signal or crash_preexisting)
        else:
            success = proc.returncode == 0

        return SuiteResult(
            name=name,
            success=success,
            tests_run=tests_run,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            execution_time=elapsed,
            output=output[-2000:],
            crashed=crash_signal is not None,
            crash_signal=crash_signal,
            crash_preexisting=crash_preexisting,
            counts_inferred=inferred,
            output_diverged=diverged,
            expected_failure=expected_failure,
            reference_returncode=reference_returncode,
        )

    except subprocess.TimeoutExpired:
        return _unrunnable_suite(
            name, f"Timed out after {timeout}s", timeout, reference,
            expected_failure, reference_returncode,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _unrunnable_suite(
            name, str(exc), time.time() - start, reference,
            expected_failure, reference_returncode,
        )


def _unrunnable_suite(
    name: str,
    error: str,
    elapsed: float,
    reference: ReferenceOutcome | None,
    expected_failure: bool,
    reference_returncode: int | None,
) -> SuiteResult:
    """A command that could not run (missing binary, timeout).

    Matches the reference only if the pre-removal build could not run it
    either, for the same reason; a binary the removal made disappear, or a run
    that now hangs, is divergence.
    """
    if reference is None:
        diverged = False
        success = False
    else:
        diverged = not (
            reference.returncode is None
            and _normalize_output(error) == (reference.error or "")
        )
        success = not diverged
    return SuiteResult(
        name=name,
        success=success,
        tests_run=0 if success else 1,
        tests_passed=0,
        tests_failed=0 if success else 1,
        execution_time=elapsed,
        error_message=error,
        output_diverged=diverged,
        expected_failure=expected_failure,
        reference_returncode=reference_returncode,
    )


def _parse_test_output(output: str, returncode: int) -> tuple[int, int, int, bool]:
    """Best-effort parse of test counts.

    Returns ``(run, passed, failed, inferred)``. ``inferred`` is True when no
    counts could be parsed and the result reflects only the exit code — the
    caller reports that distinctly rather than presenting "1 test passed" as if
    a test suite had been counted.
    """
    tests_run = 0
    tests_passed = 0
    tests_failed = 0

    match = re.search(r"test result:.*?(\d+) passed.*?(\d+) failed", output)
    if match:
        tests_passed = int(match.group(1))
        tests_failed = int(match.group(2))
        return tests_passed + tests_failed, tests_passed, tests_failed, False

    match = re.search(r"(\d+)\s+tests?\s+passed", output)
    if match:
        tests_passed = int(match.group(1))

    match = re.search(r"(\d+)\s+tests?\s+failed", output)
    if match:
        tests_failed = int(match.group(1))

    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    if match:
        tests_run = int(match.group(1))

    if tests_run == 0:
        tests_run = tests_passed + tests_failed

    if tests_run == 0:
        # Nothing parseable: represent the exit code, and say so.
        if returncode == 0:
            return 1, 1, 0, True
        return 1, 0, 1, True

    return tests_run, tests_passed, tests_failed, False
