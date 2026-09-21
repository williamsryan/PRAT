"""Tests for prat.verification module."""

from unittest.mock import MagicMock, patch

from prat.verification import (
    SuiteResult,
    VerificationStatus,
    _discover_test_commands,
    _parse_test_output,
    _run_test_suite,
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
