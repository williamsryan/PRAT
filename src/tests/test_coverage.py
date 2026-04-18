"""Tests for prat.coverage module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from prat.coverage import (
    generate_coverage,
    generate_coverage_with_adapter,
    organize_coverage_files,
    execute_for_coverage,
    CoverageResult,
)
from prat.compilation import BuildSystem


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

        assert (Path(result_dir) / "foo.c.gcov").exists()
        assert not cov_file.exists()  # moved, not copied

    def test_returns_path_string(self, tmp_path):
        result = organize_coverage_files([], "BRIDGE", True, str(tmp_path))
        assert isinstance(result, str)

    def test_missing_file_skipped_gracefully(self, tmp_path):
        result_dir = organize_coverage_files(["/nonexistent/file.gcov"], "TLS", True, str(tmp_path))
        assert Path(result_dir).exists()


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
        assert result is True
        mock_run.assert_called_once()

    def test_no_commands_returns_false(self):
        adapter = MagicMock()
        adapter.get_coverage_environment.return_value = {}
        adapter.get_execution_commands.return_value = []
        adapter.get_test_command.return_value = None

        result = execute_for_coverage(adapter, "TLS", True)
        assert result is False

    @patch("prat.coverage.subprocess.run")
    def test_timeout_counts_as_partial_success(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="make", timeout=5)
        adapter = MagicMock()
        adapter.project_path = "/fake/project"
        adapter.get_coverage_environment.return_value = {}
        adapter.get_execution_commands.return_value = [["make", "test"]]

        result = execute_for_coverage(adapter, "TLS", True)
        assert result is True  # partial coverage still useful


class TestGenerateCoverageWithAdapter:
    """Tests for generate_coverage_with_adapter()."""

    @patch("prat.coverage.organize_coverage_files")
    @patch("prat.coverage.execute_for_coverage")
    @patch("prat.coverage.subprocess.run")
    def test_returns_coverage_result(self, mock_run, mock_exec, mock_organize, tmp_path):
        mock_exec.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        mock_organize.return_value = str(tmp_path / "cov_dir")

        src = tmp_path / "src"
        src.mkdir()
        gcov_file = src / "net.c.gcov"
        gcov_file.write_text("coverage data")

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
        mock_exec.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
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
