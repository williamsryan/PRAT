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
