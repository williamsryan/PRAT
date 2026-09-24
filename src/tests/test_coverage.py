"""Tests for prat.coverage module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from prat.compilation import BuildSystem
from prat.coverage import (
    CoverageResult,
    ExecutionResult,
    _coverage_inputs,
    execute_for_coverage,
    generate_coverage,
    generate_coverage_with_adapter,
    organize_coverage_files,
)
from prat.coverage import test_plan_digest as plan_digest


class TestCoverageInputs:
    def test_prefers_dynamic_profiles(self, tmp_path):
        (tmp_path / "unit.gcno").write_text("")
        assert _coverage_inputs(tmp_path) == "*.gcno"

        (tmp_path / "unit.gcda").write_text("")
        assert _coverage_inputs(tmp_path) == "*.gcda"


class TestOrganizeCoverageFiles:
    """Tests for organize_coverage_files()."""

    def test_creates_coverage_directory(self, tmp_path):
        result_dir = organize_coverage_files([], "TLS", True, str(tmp_path))
        assert Path(result_dir).exists()
        assert "coverage_files_WITH_TLS_yes" in result_dir

    def test_disabled_uses_no_suffix(self, tmp_path):
        result_dir = organize_coverage_files([], "TLS", False, str(tmp_path))
        assert "coverage_files_WITH_TLS_no" in result_dir

    def test_moves_existing_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        cov_file = src / "foo.c.gcov"
        cov_file.write_text("# coverage data")

        result_dir = organize_coverage_files([str(cov_file)], "TLS", True, str(tmp_path))

        assert len(list(Path(result_dir).glob("*-foo.c.gcov"))) == 1
        assert not cov_file.exists()  # moved, not copied

    def test_returns_path_string(self, tmp_path):
        result = organize_coverage_files([], "BRIDGE", True, str(tmp_path))
        assert isinstance(result, str)

    def test_missing_file_fails_staging(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            organize_coverage_files(
                ["/nonexistent/file.gcov"], "TLS", True, str(tmp_path)
            )

    def test_rerun_clears_stale_coverage_artifacts(self, tmp_path):
        result_dir = Path(
            organize_coverage_files([], "TLS", True, str(tmp_path))
        )
        (result_dir / "stale.gcov").write_text("old")

        organize_coverage_files([], "TLS", True, str(tmp_path))

        assert not (result_dir / "stale.gcov").exists()

    def test_same_source_from_two_objects_is_merged_not_overwritten(self, tmp_path):
        """Mosquitto compiles lib/*.c into both libmosquitto and the broker, so
        gcov yields one .gcov per object for the same source. A line executed
        in either compilation unit is executed."""
        from prat.gcov import parse_gcov

        lib_dir = tmp_path / "lib"
        src_dir = tmp_path / "srcobj"
        lib_dir.mkdir()
        src_dir.mkdir()
        header = "        -:    0:Source:lib/net.c\n"
        (lib_dir / "net.c.gcov").write_text(
            header
            + "        3:    1:int a;\n"
            + "    #####:    2:int b;\n"
            + "        -:    3:/* only code in the broker build */\n"
            + "        -:    4:}\n"
        )
        (src_dir / "net.c.gcov").write_text(
            header
            + "        2:    1:int a;\n"
            + "        7:    2:int b;\n"
            + "    #####:    3:/* only code in the broker build */\n"
            + "        -:    4:}\n"
        )

        result_dir = organize_coverage_files(
            [str(lib_dir / "net.c.gcov"), str(src_dir / "net.c.gcov")],
            "TLS", True, str(tmp_path),
        )

        staged = list(Path(result_dir).glob("*-net.c.gcov"))
        assert len(staged) == 1
        parsed = parse_gcov(str(staged[0]))
        assert parsed.executed == {1, 2}
        assert parsed.never_executed == {3}
        assert parsed.non_executable == {4}
        assert "        5:    1:" in staged[0].read_text()


class TestGenerateCoverage:
    """Tests for generate_coverage()."""

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.subprocess.run")
    @patch("prat.coverage._detect_coverage_tool")
    def test_unknown_build_system_fails(self, mock_detect, mock_run, mock_organize):
        result = generate_coverage("/proj", "TLS", True, BuildSystem.UNKNOWN)
        assert result.success is False
        assert "Unsupported build system" in result.error_message

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.subprocess.run")
    @patch("prat.coverage._detect_coverage_tool")
    def test_make_generates_coverage(self, mock_detect, mock_run, mock_organize, tmp_path):
        mock_detect.return_value = "gcov"
        mock_run.return_value = MagicMock(returncode=0)
        mock_organize.return_value = str(tmp_path / "cov_dir")

        src = tmp_path / "src"
        src.mkdir()
        gcov_file = src / "foo.c.gcov"
        gcov_file.write_text("data")

        with patch("prat.coverage._generate_coverage_make") as mock_make:
            mock_make.return_value = ([str(gcov_file)], [])
            result = generate_coverage(str(tmp_path), "TLS", True, BuildSystem.MAKE)

        assert result.success is True
        assert len(result.coverage_files) == 1

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage._detect_coverage_tool")
    def test_no_coverage_files_means_failure(self, mock_detect, mock_organize, tmp_path):
        mock_detect.return_value = "gcov"
        mock_organize.return_value = str(tmp_path / "cov_dir")

        with patch("prat.coverage._generate_coverage_make") as mock_make:
            mock_make.return_value = ([], [])
            result = generate_coverage(str(tmp_path), "TLS", True, BuildSystem.MAKE)

        assert result.success is False
        assert result.error_message is not None


class TestExecuteForCoverage:
    """Tests for execute_for_coverage()."""

    @patch("prat.coverage.subprocess.run")
    def test_runs_execution_commands(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}
        adapter.get_execution_commands.return_value = [["make", "test"]]

        result = execute_for_coverage(adapter, "TLS", True)
        assert result.success is True
        assert result.succeeded == 1
        mock_run.assert_called_once()

    def test_no_commands_returns_false(self):
        adapter = MagicMock()
        adapter.get_coverage_environment.return_value = {}
        adapter.get_execution_commands.return_value = []
        adapter.get_test_command.return_value = None

        result = execute_for_coverage(adapter, "TLS", True)
        assert result.success is False

    @patch("prat.coverage.subprocess.run")
    def test_timeout_invalidates_dynamic_coverage(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="make", timeout=5)
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}
        adapter.get_execution_commands.return_value = [["make", "test"]]

        result = execute_for_coverage(adapter, "TLS", True)
        assert result.success is False
        assert result.timed_out == 1

    @patch("prat.coverage.subprocess.run")
    def test_a_fixed_plan_is_run_instead_of_the_polarity_workload(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}
        adapter.get_execution_commands.return_value = [["polarity", "specific"]]

        result = execute_for_coverage(
            adapter, "TLS", False, execution_commands=[["fixed", "T"]]
        )

        adapter.get_execution_commands.assert_not_called()
        assert mock_run.call_args.args[0] == ["fixed", "T"]
        assert result.executed == [["fixed", "T"]]

    @patch("prat.coverage.subprocess.run")
    def test_failures_are_fatal_for_b_all(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1, stderr="tls: no such listener", stdout=""),
        ]
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}

        result = execute_for_coverage(
            adapter, "TLS", True,
            execution_commands=[["plain"], ["tls"]],
        )

        assert result.success is False
        assert result.failed == 1
        assert "tls: no such listener" in result.error_message()

    @patch("prat.coverage.subprocess.run")
    def test_failures_are_tolerated_and_recorded_for_b_f(self, mock_run):
        """Algorithm 1 runs the same T against B_f; f's own tests cannot pass
        there. Coverage comes from the rest of T, and the failures stay on
        record."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1, stderr="tls: no such listener", stdout=""),
        ]
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}

        result = execute_for_coverage(
            adapter, "TLS", False,
            execution_commands=[["plain"], ["tls"]],
            allow_failures=True,
        )

        assert result.success is True
        assert result.succeeded == 1
        assert result.failed == 1
        assert result.executed == [["plain"], ["tls"]]
        assert result.errors == ["tls: tls: no such listener"]

    @patch("prat.coverage.subprocess.run")
    def test_tolerance_still_requires_something_to_have_run(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="", stdout="")
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}

        result = execute_for_coverage(
            adapter, "TLS", False,
            execution_commands=[["tls"]],
            allow_failures=True,
        )

        assert result.success is False


class TestGenerateCoverageWithAdapter:
    """Tests for generate_coverage_with_adapter()."""

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.execute_for_coverage")
    @patch("prat.coverage.subprocess.run")
    def test_returns_coverage_result(self, mock_run, mock_exec, mock_organize, tmp_path):
        mock_exec.return_value = ExecutionResult(commands=1, succeeded=1)
        mock_organize.side_effect = organize_coverage_files

        src = tmp_path / "src"
        src.mkdir()
        gcov_file = src / "net.c.gcov"
        def run_gcov(*_args, **_kwargs):
            gcov_file.write_text("coverage data")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_gcov

        adapter = MagicMock()
        adapter.project_path = str(tmp_path)
        adapter.coverage_tool = "gcov"
        adapter.source_directories = ["src"]

        result = generate_coverage_with_adapter(adapter, "TLS", True)

        assert isinstance(result, CoverageResult)
        assert result.success is True

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.execute_for_coverage")
    @patch("prat.coverage.subprocess.run")
    def test_records_the_digest_of_the_plan_actually_run(
        self, mock_run, mock_exec, mock_organize, tmp_path
    ):
        """The caller's digest is not trusted; what ran is what is recorded,
        with tolerated failures carried into the result."""
        mock_exec.return_value = ExecutionResult(
            commands=2, succeeded=1, failed=1,
            errors=["tls: exit code 1"],
            executed=[["plain"], ["tls"]],
            failures_tolerated=True,
        )
        mock_organize.side_effect = organize_coverage_files
        src = tmp_path / "src"
        src.mkdir()
        gcov_file = src / "net.c.gcov"

        def run_gcov(*_args, **_kwargs):
            gcov_file.write_text("coverage data")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_gcov
        adapter = MagicMock()
        adapter.project_path = str(tmp_path)
        adapter.coverage_tool = "gcov"
        adapter.source_directories = ["src"]
        adapter.coverage_command_executes_tests.return_value = False

        result = generate_coverage_with_adapter(
            adapter, "TLS", False,
            execution_commands=[["plain"], ["tls"]],
            test_plan_id="caller-supplied",
            allow_test_failures=True,
        )

        assert result.success is True
        assert result.test_plan_id == plan_digest([["plain"], ["tls"]])
        assert result.test_failures_tolerated is True
        assert result.execution_errors == ["tls: exit code 1"]
        assert result.execution_failed == 1
        assert mock_exec.call_args.kwargs["allow_failures"] is True

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.execute_for_coverage")
    @patch("prat.coverage.subprocess.run")
    def test_no_gcov_files_means_failure(self, mock_run, mock_exec, mock_organize, tmp_path):
        mock_exec.return_value = ExecutionResult(commands=1, succeeded=1)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_organize.return_value = str(tmp_path / "cov_dir")

        src = tmp_path / "src"
        src.mkdir()
        # No .gcov files created

        adapter = MagicMock()
        adapter.project_path = str(tmp_path)
        adapter.coverage_tool = "gcov"
        adapter.source_directories = ["src"]

        result = generate_coverage_with_adapter(adapter, "TLS", True)

        assert result.success is False

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.execute_for_coverage")
    @patch("prat.coverage.subprocess.run")
    def test_gcov_failure_invalidates_partial_coverage(
        self, mock_run, mock_exec, mock_organize, tmp_path
    ):
        mock_exec.return_value = ExecutionResult(commands=1, succeeded=1)
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="profile mismatch"
        )
        mock_organize.return_value = str(tmp_path / "cov_dir")
        (tmp_path / "src").mkdir()

        adapter = MagicMock()
        adapter.project_path = str(tmp_path)
        adapter.coverage_tool = "gcov"
        adapter.source_directories = ["src"]

        result = generate_coverage_with_adapter(adapter, "TLS", True)

        assert result.success is False
        assert "incomplete" in (result.error_message or "")
