"""Tests for prat.verification module."""

from unittest.mock import MagicMock, patch

from prat.verification import (
    ReferenceOutcome,
    SuiteResult,
    VerificationStatus,
    _discover_test_commands,
    _parse_test_output,
    _run_test_suite,
    capture_reference_outputs,
    verify_correctness,
)


class TestParseTestOutput:
    """Tests for test output parsing."""

    def test_cargo_format(self):
        output = "test result: ok. 42 passed; 0 failed; 0 ignored"
        run, passed, failed, inferred = _parse_test_output(output, 0)
        assert (run, passed, failed) == (42, 42, 0)
        assert inferred is False

    def test_cargo_with_failures(self):
        output = "test result: FAILED. 38 passed; 4 failed; 0 ignored"
        run, passed, failed, inferred = _parse_test_output(output, 1)
        assert (run, passed, failed) == (42, 38, 4)
        assert inferred is False

    def test_generic_format(self):
        output = "15 tests passed\n2 tests failed\n"
        run, passed, failed, inferred = _parse_test_output(output, 1)
        assert (run, passed, failed) == (17, 15, 2)
        assert inferred is False

    def test_ran_format(self):
        output = "Ran 10 tests\nOK\n"
        run, _passed, _failed, inferred = _parse_test_output(output, 0)
        assert run == 10
        assert inferred is False

    def test_unparseable_output_is_flagged_as_inferred(self):
        """"1 test passed" must not be presented as a counted suite result."""
        run, passed, failed, inferred = _parse_test_output("some random output", 0)
        assert (run, passed, failed) == (1, 1, 0)
        assert inferred is True

    def test_unparseable_failure_is_flagged_as_inferred(self):
        run, passed, failed, inferred = _parse_test_output("error!", 1)
        assert (run, passed, failed) == (1, 0, 1)
        assert inferred is True


class TestDiscoverTestCommands:

    def test_override_takes_priority(self):
        commands = [["make", "test"], ["make", "check"]]
        suites = _discover_test_commands("/fake", override=commands)
        assert len(suites) == 2
        assert suites[0][1] == ["make", "test"]

    def test_adapter_test_command(self):
        adapter = MagicMock()
        adapter.get_test_command.return_value = ["make", "utest"]
        suites = _discover_test_commands("/fake", adapter=adapter)
        assert any(cmd == ["make", "utest"] for _, cmd in suites)

    def test_cargo_project(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        suites = _discover_test_commands(str(tmp_path))
        assert any("cargo" in cmd[0] for _, cmd in suites)


class TestRunTestSuite:

    @patch("prat.verification.subprocess.run")
    def test_passing_suite(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Ran 5 tests\nOK\n",
            stderr="",
        )
        result = _run_test_suite("unit", ["make", "test"], "/fake", 60)
        assert result.success is True
        assert result.tests_run == 5

    @patch("prat.verification.subprocess.run")
    def test_failing_suite(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="3 tests passed\n2 tests failed\n",
            stderr="",
        )
        result = _run_test_suite("unit", ["make", "test"], "/fake", 60)
        assert result.success is False
        assert result.tests_failed == 2

    @patch("prat.verification.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=60)
        result = _run_test_suite("unit", ["make", "test"], "/fake", 60)
        assert result.success is False
        assert "Timed out" in result.error_message


class TestReferenceOracle:
    """Verification re-runs the *fixed* T (paper, Feature Removal), so T
    contains the removed feature's own tests. The oracle is the pre-removal
    build in the same configuration: every outcome must be reproduced."""

    @patch("prat.verification.subprocess.run")
    def test_capture_records_failures_as_expected_outcomes(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="plain ok\n", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="tls: unknown option cafile\n"),
        ]

        refs = capture_reference_outputs(
            "/fake", test_commands=[["plain"], ["tls"]]
        )

        assert refs["custom-0"].passed is True
        assert refs["custom-0"].output == "plain ok"
        assert refs["custom-1"].passed is False
        assert refs["custom-1"].returncode == 1
        assert "unknown option" in refs["custom-1"].output

    @patch("prat.verification.subprocess.run")
    def test_capture_records_a_command_that_cannot_run(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="ok", stderr=""),
            FileNotFoundError("aom_build/aomenc: No such file"),
        ]

        refs = capture_reference_outputs(
            "/fake", test_commands=[["aomdec"], ["aomenc"]]
        )

        assert refs["custom-1"].returncode is None
        assert "aomenc" in (refs["custom-1"].error or "")

    @patch("prat.verification.subprocess.run")
    def test_capture_refuses_a_reference_in_which_nothing_passes(self, mock_run):
        import pytest

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")

        with pytest.raises(RuntimeError, match="no behaviour .* to preserve"):
            capture_reference_outputs("/fake", test_commands=[["tls"]])

    @patch("prat.verification.subprocess.run")
    def test_expected_failure_reproduced_is_preserved_behaviour(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="tls: unknown option cafile\n"
        )
        reference = ReferenceOutcome(returncode=1, output="tls: unknown option cafile")

        result = _run_test_suite("tls", ["tls"], "/fake", 60, reference=reference)

        assert result.expected_failure is True
        assert result.output_diverged is False
        assert result.success is True
        assert result.reference_returncode == 1

    @patch("prat.verification.subprocess.run")
    def test_expected_failure_that_now_passes_is_divergence(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="tls ok\n", stderr="")
        reference = ReferenceOutcome(returncode=1, output="tls: unknown option cafile")

        result = _run_test_suite("tls", ["tls"], "/fake", 60, reference=reference)

        assert result.expected_failure is True
        assert result.output_diverged is True
        assert result.success is False

    @patch("prat.verification.subprocess.run")
    def test_passing_reference_that_now_fails_is_divergence(self, mock_run):
        mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="assert\n")

        result = _run_test_suite(
            "unit", ["make", "test"], "/fake", 60,
            reference=ReferenceOutcome(returncode=0, output="Ran 5 tests\nOK"),
        )

        assert result.expected_failure is False
        assert result.output_diverged is True
        assert result.success is False

    @patch("prat.verification.subprocess.run")
    def test_same_output_different_exit_code_is_divergence(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="Ran 5 tests\nOK\n", stderr="")

        result = _run_test_suite(
            "unit", ["make", "test"], "/fake", 60,
            reference=ReferenceOutcome(returncode=0, output="Ran 5 tests\nOK"),
        )

        assert result.output_diverged is True

    @patch("prat.verification.subprocess.run")
    def test_legacy_string_reference_means_a_passing_run(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Ran 5 tests\nOK\n", stderr="")

        result = _run_test_suite(
            "unit", ["make", "test"], "/fake", 60, reference="Ran 5 tests\nOK"
        )

        assert result.success is True
        assert result.output_diverged is False
        assert result.expected_failure is False

    @patch("prat.verification.subprocess.run")
    def test_a_binary_missing_before_and_after_is_preserved(self, mock_run):
        mock_run.side_effect = FileNotFoundError("aom_build/aomenc: No such file")
        reference = ReferenceOutcome(
            returncode=None, output="", error="aom_build/aomenc: No such file"
        )

        result = _run_test_suite("enc", ["aomenc"], "/fake", 60, reference=reference)

        assert result.success is True
        assert result.expected_failure is True
        assert result.output_diverged is False

    @patch("prat.verification.subprocess.run")
    def test_a_binary_that_removal_made_disappear_is_divergence(self, mock_run):
        mock_run.side_effect = FileNotFoundError("aom_build/aomdec: No such file")

        result = _run_test_suite(
            "dec", ["aomdec"], "/fake", 60,
            reference=ReferenceOutcome(returncode=0, output="decoded"),
        )

        assert result.success is False
        assert result.output_diverged is True
        assert result.tests_failed == 1

    @patch("prat.verification.subprocess.run")
    def test_crash_present_before_removal_is_preexisting(self, mock_run):
        mock_run.return_value = MagicMock(returncode=-11, stdout="", stderr="")
        reference = ReferenceOutcome(
            returncode=-11, output="", crash_signal="SIGSEGV"
        )

        result = _run_test_suite("t", ["t"], "/fake", 60, reference=reference)

        assert result.crashed is True
        assert result.crash_preexisting is True
        assert result.success is True

    @patch("prat.verification._run_test_suite")
    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_expected_failures_do_not_count_against_the_verdict(
        self, mock_rebuild, mock_discover, mock_suite
    ):
        mock_rebuild.return_value = True
        mock_discover.return_value = [("plain", ["plain"]), ("tls", ["tls"])]
        mock_suite.side_effect = [
            SuiteResult(
                name="plain", success=True, tests_run=5, tests_passed=5,
                tests_failed=0, execution_time=1.0,
            ),
            SuiteResult(
                name="tls", success=True, tests_run=1, tests_passed=0,
                tests_failed=1, execution_time=1.0, counts_inferred=True,
                expected_failure=True, reference_returncode=1,
            ),
        ]

        result = verify_correctness(
            "/fake/project",
            test_commands=[["plain"], ["tls"]],
            reference_outputs={
                "plain": ReferenceOutcome(0, "ok"),
                "tls": ReferenceOutcome(1, "unknown option"),
            },
        )

        assert result.status is VerificationStatus.PASSED
        assert result.expected_failures == ["tls"]
        assert result.total_tests_run == 5
        assert result.total_tests_failed == 0
        assert result.pass_rate == 100.0

    @patch("prat.verification._run_test_suite")
    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_expected_failure_that_diverged_fails_the_verdict(
        self, mock_rebuild, mock_discover, mock_suite
    ):
        mock_rebuild.return_value = True
        mock_discover.return_value = [("plain", ["plain"]), ("tls", ["tls"])]
        mock_suite.side_effect = [
            SuiteResult(
                name="plain", success=True, tests_run=5, tests_passed=5,
                tests_failed=0, execution_time=1.0,
            ),
            SuiteResult(
                name="tls", success=False, tests_run=1, tests_passed=1,
                tests_failed=0, execution_time=1.0, counts_inferred=True,
                expected_failure=True, output_diverged=True,
            ),
        ]

        result = verify_correctness("/fake/project", test_commands=[["plain"], ["tls"]])

        assert result.status is VerificationStatus.FAILED
        assert result.diverged_suites == ["tls"]

    @patch("prat.verification._run_test_suite")
    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_preexisting_crash_is_reported_but_is_not_a_new_crash(
        self, mock_rebuild, mock_discover, mock_suite
    ):
        mock_rebuild.return_value = True
        mock_discover.return_value = [("plain", ["plain"]), ("t", ["t"])]
        mock_suite.side_effect = [
            SuiteResult(
                name="plain", success=True, tests_run=5, tests_passed=5,
                tests_failed=0, execution_time=1.0,
            ),
            SuiteResult(
                name="t", success=True, tests_run=1, tests_passed=0,
                tests_failed=1, execution_time=1.0, crashed=True,
                crash_signal="SIGSEGV", crash_preexisting=True,
                expected_failure=True,
            ),
        ]

        result = verify_correctness("/fake/project", test_commands=[["plain"], ["t"]])

        assert result.status is VerificationStatus.PASSED
        assert result.crashes == []
        assert result.preexisting_crashes == ["t: SIGSEGV"]


class TestVerifyCorrectness:

    @patch("prat.verification._run_test_suite")
    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_all_passing(self, mock_rebuild, mock_discover, mock_suite):
        mock_rebuild.return_value = True
        mock_discover.return_value = [("unit", ["make", "test"])]
        mock_suite.return_value = SuiteResult(
            name="unit", success=True,
            tests_run=10, tests_passed=10, tests_failed=0,
            execution_time=1.0,
        )

        result = verify_correctness("/fake/project")

        assert result.success is True
        assert result.compiles is True
        assert result.total_tests_passed == 10
        assert result.pass_rate == 100.0

    @patch("prat.verification._rebuild")
    def test_compilation_failure(self, mock_rebuild):
        mock_rebuild.return_value = False

        result = verify_correctness("/fake/project")

        assert result.success is False
        assert result.compiles is False
        assert "failed to compile" in result.error_message

    @patch("prat.verification._run_test_suite")
    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_test_failures(self, mock_rebuild, mock_discover, mock_suite):
        mock_rebuild.return_value = True
        mock_discover.return_value = [("unit", ["make", "test"])]
        mock_suite.return_value = SuiteResult(
            name="unit", success=False,
            tests_run=10, tests_passed=8, tests_failed=2,
            execution_time=1.0,
        )

        result = verify_correctness("/fake/project")

        assert result.success is False
        assert result.total_tests_failed == 2

    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_no_tests_is_inconclusive_not_a_pass(self, mock_rebuild, mock_discover):
        """Compiling is necessary but not sufficient evidence of correctness."""
        mock_rebuild.return_value = True
        mock_discover.return_value = []

        result = verify_correctness("/fake/project")

        assert result.status is VerificationStatus.INCONCLUSIVE
        assert result.success is False
        assert result.compiles is True
        assert result.total_tests_run == 0
        assert "unverified" in (result.error_message or "")

    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_no_tests_can_be_accepted_explicitly(self, mock_rebuild, mock_discover):
        mock_rebuild.return_value = True
        mock_discover.return_value = []

        result = verify_correctness("/fake/project", require_tests=False)

        assert result.status is VerificationStatus.INCONCLUSIVE
        assert result.success is True

    @patch("prat.verification.replay_tests")
    @patch("prat.verification._discover_test_commands")
    @patch("prat.verification._rebuild")
    def test_klee_replay_integration(self, mock_rebuild, mock_discover, mock_replay,
                                     tmp_path):
        from prat.symbolic import SymbolicResult

        mock_rebuild.return_value = True
        mock_discover.return_value = []
        mock_replay.return_value = {
            "test001.ktest": True,
            "test002.ktest": True,
            "test003.ktest": False,
        }

        sym_result = SymbolicResult(
            success=True,
            test_cases=["/tmp/test001.ktest", "/tmp/test002.ktest", "/tmp/test003.ktest"],
            test_count=3,
        )
        # The binary must exist: replaying against a missing target would report
        # passes for tests that never ran.
        binary = tmp_path / "broker"
        binary.write_bytes(b"\x7fELF")

        result = verify_correctness(
            "/fake/project",
            symbolic_result=sym_result,
            binary_path=str(binary),
        )

        assert result.total_tests_run == 3
        assert result.total_tests_passed == 2
        assert result.total_tests_failed == 1
        assert result.success is False  # 1 failure
