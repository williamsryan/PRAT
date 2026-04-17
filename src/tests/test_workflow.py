"""Tests for prat.workflow module — integration-level with mocked externals."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from prat.workflow import (
    run_complete_workflow,
    WorkflowResult,
    WorkflowCheckpoint,
)
from prat.compilation import BuildSystem, CompilationResult
from prat.coverage import CoverageResult
from prat.diff import DiffResult
from prat.extraction import ExtractionResult
from prat.environment import EnvironmentResult


def _make_env_result(success=True, missing=None):
    return EnvironmentResult(
        success=success,
        available_tools={"gcc": True, "make": True},
        missing_tools=missing or [],
        error_message=None if success else "Missing deps",
    )


def _make_comp_result(success=True, bs=BuildSystem.MAKE):
    return CompilationResult(
        success=success,
        binary_path="/fake/binary" if success else None,
        error_message=None if success else "compile error",
        compilation_time=1.5,
        coverage_enabled=True,
        build_system=bs,
    )


def _make_cov_result(success=True):
    return CoverageResult(
        success=success,
        coverage_files=["a.gcov", "b.gcov"] if success else [],
        coverage_dir="/fake/cov_dir",
        missing_files=[],
        error_message=None if success else "no coverage",
    )


def _make_diff_result(success=True):
    return DiffResult(
        success=success,
        diff_dir="/fake/diff_dir",
        diff_files=["a.gcov", "b.gcov"] if success else [],
        feature_only_files=["tls.c"],
        total_diffs=2 if success else 0,
        error_message=None if success else "diff error",
    )


def _make_ext_result(success=True):
    return ExtractionResult(
        success=success,
        file_line_counts={"net.c": 10, "tls.c": 25} if success else {},
        total_removable_lines=35 if success else 0,
        file_line_numbers={"net.c": [1, 2], "tls.c": [10]} if success else {},
        file_line_content={"net.c": ["code1", "code2"], "tls.c": ["code3"]} if success else {},
        error_message=None if success else "extract error",
    )


class TestRunCompleteWorkflow:
    """Tests for run_complete_workflow()."""

    @patch("prat.workflow.generate_html_diffs")
    @patch("prat.workflow.generate_dot_graph")
    @patch("prat.workflow.generate_html_report")
    @patch("prat.workflow.extract_features")
    @patch("prat.workflow.diff_coverage_files")
    @patch("prat.workflow.generate_coverage")
    @patch("prat.workflow.compile_project")
    @patch("prat.workflow.get_adapter", return_value=None)
    @patch("prat.workflow.verify_dependencies")
    def test_successful_workflow(
        self, mock_deps, mock_adapter, mock_compile, mock_cov,
        mock_diff, mock_extract, mock_html, mock_dot, mock_diffs,
        tmp_path,
    ):
        mock_deps.return_value = _make_env_result()
        mock_compile.return_value = _make_comp_result()
        mock_cov.return_value = _make_cov_result()
        mock_diff.return_value = _make_diff_result()
        mock_extract.return_value = _make_ext_result()

        result = run_complete_workflow(
            project_path=str(tmp_path),
            feature="TLS",
            output_dir=str(tmp_path),
        )

        assert result.success is True
        assert result.checkpoint == WorkflowCheckpoint.COMPLETE
        assert result.extraction_result.total_removable_lines == 35
        assert result.total_time > 0

    @patch("prat.workflow.get_adapter", return_value=None)
    @patch("prat.workflow.verify_dependencies")
    def test_stops_on_missing_deps(self, mock_deps, mock_adapter, tmp_path):
        mock_deps.return_value = _make_env_result(
            success=False, missing=["gcc", "gcov"]
        )

        result = run_complete_workflow(
            project_path=str(tmp_path),
            feature="TLS",
            output_dir=str(tmp_path),
        )

        assert result.success is False
        assert result.checkpoint == WorkflowCheckpoint.START
        assert "gcc" in result.error_message

    @patch("prat.workflow.generate_coverage")
    @patch("prat.workflow.compile_project")
    @patch("prat.workflow.get_adapter", return_value=None)
    @patch("prat.workflow.verify_dependencies")
    def test_stops_on_compile_failure(
        self, mock_deps, mock_adapter, mock_compile, mock_cov, tmp_path
    ):
        mock_deps.return_value = _make_env_result()
        mock_compile.return_value = _make_comp_result(success=False)

        result = run_complete_workflow(
            project_path=str(tmp_path),
            feature="TLS",
            output_dir=str(tmp_path),
        )

        assert result.success is False
        assert result.checkpoint == WorkflowCheckpoint.COMPILE_ENABLED

    @patch("prat.workflow.generate_html_diffs")
    @patch("prat.workflow.generate_dot_graph")
    @patch("prat.workflow.generate_html_report")
    @patch("prat.workflow.extract_features")
    @patch("prat.workflow.diff_coverage_files")
    @patch("prat.workflow.generate_coverage_with_adapter")
    @patch("prat.workflow.compile_with_adapter")
    @patch("prat.workflow.verify_dependencies")
    def test_uses_adapter_when_provided(
        self, mock_deps, mock_comp_adapt, mock_cov_adapt,
        mock_diff, mock_extract, mock_html, mock_dot, mock_diffs,
        tmp_path,
    ):
        mock_deps.return_value = _make_env_result()
        mock_comp_adapt.return_value = _make_comp_result()
        mock_cov_adapt.return_value = _make_cov_result()
        mock_diff.return_value = _make_diff_result()
        mock_extract.return_value = _make_ext_result()

        fake_adapter = MagicMock()
        fake_adapter.build_system = BuildSystem.MAKE
        fake_adapter.coverage_tool = "llvm-cov-9"
        fake_adapter.source_directories = ["src", "lib"]

        result = run_complete_workflow(
            project_path=str(tmp_path),
            feature="TLS",
            output_dir=str(tmp_path),
            adapter=fake_adapter,
        )

        assert result.success is True
        # Should have called adapter-based functions
        assert mock_comp_adapt.call_count == 2  # enabled + disabled
        assert mock_cov_adapt.call_count == 2

    @patch("prat.workflow.generate_html_diffs")
    @patch("prat.workflow.generate_dot_graph")
    @patch("prat.workflow.generate_html_report")
    @patch("prat.workflow.extract_features")
    @patch("prat.workflow.diff_coverage_files")
    @patch("prat.workflow.generate_coverage")
    @patch("prat.workflow.compile_project")
    @patch("prat.workflow.get_adapter", return_value=None)
    @patch("prat.workflow.verify_dependencies")
    def test_result_contains_all_fields(
        self, mock_deps, mock_adapter, mock_compile, mock_cov,
        mock_diff, mock_extract, mock_html, mock_dot, mock_diffs,
        tmp_path,
    ):
        mock_deps.return_value = _make_env_result()
        mock_compile.return_value = _make_comp_result()
        mock_cov.return_value = _make_cov_result()
        mock_diff.return_value = _make_diff_result()
        mock_extract.return_value = _make_ext_result()

        result = run_complete_workflow(
            project_path=str(tmp_path),
            feature="TLS",
            output_dir=str(tmp_path),
        )

        assert isinstance(result, WorkflowResult)
        assert result.project is not None
        assert result.feature == "TLS"
        assert result.compilation_enabled is not None
        assert result.compilation_disabled is not None
        assert result.coverage_enabled is not None
        assert result.coverage_disabled is not None
        assert result.diff_result is not None
        assert result.extraction_result is not None
