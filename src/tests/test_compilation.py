"""Tests for prat.compilation module."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from prat.compilation import (
    detect_build_system,
    compile_project,
    compile_with_adapter,
    BuildSystem,
    CompilationResult,
)


class TestDetectBuildSystem:
    """Tests for detect_build_system()."""

    def test_detect_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        assert detect_build_system(str(tmp_path)) == BuildSystem.CARGO

    def test_detect_cmake(self, tmp_path):
        (tmp_path / "CMakeLists.txt").touch()
        assert detect_build_system(str(tmp_path)) == BuildSystem.CMAKE

    def test_detect_autotools(self, tmp_path):
        (tmp_path / "configure").touch()
        assert detect_build_system(str(tmp_path)) == BuildSystem.AUTOTOOLS

    def test_detect_make(self, tmp_path):
        (tmp_path / "Makefile").touch()
        assert detect_build_system(str(tmp_path)) == BuildSystem.MAKE

    def test_detect_unknown(self, tmp_path):
        assert detect_build_system(str(tmp_path)) == BuildSystem.UNKNOWN

    def test_cargo_takes_priority_over_cmake(self, tmp_path):
        """Cargo.toml checked before CMakeLists.txt."""
        (tmp_path / "Cargo.toml").touch()
        (tmp_path / "CMakeLists.txt").touch()
        assert detect_build_system(str(tmp_path)) == BuildSystem.CARGO


class TestCompileProject:
    """Tests for compile_project()."""

    def test_unknown_build_system_fails(self, tmp_path):
        result = compile_project(str(tmp_path), "TLS", True)
        assert result.success is False
        assert "Unable to detect" in result.error_message

    @patch("prat.compilation.subprocess.run")
    def test_make_compilation_success(self, mock_run, tmp_path):
        (tmp_path / "Makefile").touch()
        (tmp_path / "src").mkdir()

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = compile_project(str(tmp_path), "TLS", True)

        assert result.success is True
        assert result.build_system == BuildSystem.MAKE
        assert result.coverage_enabled is True

    @patch("prat.compilation.subprocess.run")
    def test_make_compilation_failure(self, mock_run, tmp_path):
        (tmp_path / "Makefile").touch()

        # Clean succeeds, compile fails
        mock_run.side_effect = [
            MagicMock(returncode=0),  # clean
            MagicMock(returncode=1, stderr="error: missing header"),  # compile
        ]

        result = compile_project(str(tmp_path), "TLS", True)

        assert result.success is False
        assert "missing header" in result.error_message


class TestCompileWithAdapter:
    """Tests for compile_with_adapter()."""

    @patch("prat.compilation.subprocess.run")
    def test_successful_compile(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        adapter = MagicMock()
        adapter.project_path = Path("/fake/project")
        adapter.build_system = BuildSystem.MAKE
        adapter.get_clean_command.return_value = ["make", "clean"]
        adapter.get_compile_command.return_value = ["make", "binary", "WITH_TLS=yes"]
        adapter.get_test_command.return_value = None
        adapter.get_binary_path.return_value = "/fake/project/src/mosquitto"
        adapter.get_coverage_environment.return_value = {}

        result = compile_with_adapter(adapter, "TLS", True)

        assert result.success is True
        assert result.binary_path == "/fake/project/src/mosquitto"
        assert result.build_system == BuildSystem.MAKE
        adapter.get_clean_command.assert_called_once()
        adapter.get_compile_command.assert_called_once_with("TLS", True, with_coverage=True)

    @patch("prat.compilation.subprocess.run")
    def test_compile_failure(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # clean
            MagicMock(returncode=1, stderr="fatal error"),  # compile
        ]

        adapter = MagicMock()
        adapter.project_path = Path("/fake/project")
        adapter.build_system = BuildSystem.MAKE
        adapter.get_clean_command.return_value = ["make", "clean"]
        adapter.get_compile_command.return_value = ["make", "binary"]
        adapter.get_coverage_environment.return_value = {}

        result = compile_with_adapter(adapter, "TLS", True)

        assert result.success is False
        assert "fatal error" in result.error_message

    @patch("prat.compilation.subprocess.run")
    def test_runs_tests_when_requested(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        adapter = MagicMock()
        adapter.project_path = Path("/fake/project")
        adapter.build_system = BuildSystem.MAKE
        adapter.get_clean_command.return_value = ["make", "clean"]
        adapter.get_compile_command.return_value = ["make", "binary"]
        adapter.get_test_command.return_value = ["make", "test"]
        adapter.get_binary_path.return_value = None
        adapter.get_coverage_environment.return_value = {}

        result = compile_with_adapter(adapter, "TLS", True, run_tests=True)

        assert result.success is True
        # clean + compile + test = 3 calls
        assert mock_run.call_count == 3
