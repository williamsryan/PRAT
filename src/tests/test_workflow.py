"""Tests for prat.workflow — the single-feature pipeline orchestration."""

from unittest.mock import MagicMock, patch

import pytest

from prat.compilation import BuildSystem, CompilationResult
from prat.coverage import CoverageResult
from prat.environment import EnvironmentResult
from prat.removal import RemovalResult
from prat.verification import VerificationResult, VerificationStatus
from prat.workflow import WorkflowCheckpoint, WorkflowResult, run_complete_workflow

from .test_mapping import write_gcov


@pytest.fixture
def coverage_dirs(tmp_path):
    """An enabled/disabled coverage pair with one feature line (line 10)."""
    enabled = tmp_path / "cov_on"
    disabled = tmp_path / "cov_off"
    write_gcov(enabled, "src/net.c", {10: "4", 14: "9"})
    write_gcov(disabled, "src/net.c", {14: "9"})
    return enabled, disabled


@pytest.fixture
def happy_path(coverage_dirs, tmp_path):
    """Patch out every external step so the mapping logic can be exercised."""
    enabled, disabled = coverage_dirs

    def fake_coverage(*args, **kwargs):
        state = kwargs.get("enabled", args[2] if len(args) > 2 else True)
        target = enabled if state else disabled
        return CoverageResult(
            success=True,
            coverage_files=[str(p) for p in target.iterdir()],
            coverage_dir=str(target),
            missing_files=[],
            dynamic_execution=True,
        )

    compilation = CompilationResult(
        success=True,
        binary_path=str(tmp_path / "bin"),
        error_message=None,
        compilation_time=0.1,
        coverage_enabled=True,
        build_system=BuildSystem.MAKE,
    )
    adapter = MagicMock()
    adapter.build_system = BuildSystem.MAKE
    adapter.coverage_tool = "gcov"
    adapter.source_directories = ["src"]

    with (
        patch("prat.workflow.verify_dependencies",
              return_value=EnvironmentResult(success=True, available_tools={}, missing_tools=[])),
        patch("prat.workflow.get_adapter", return_value=adapter),
        patch("prat.workflow.compile_with_adapter", return_value=compilation),
        patch(
            "prat.workflow.generate_coverage_with_adapter",
            side_effect=fake_coverage,
        ),
        patch("prat.workflow.generate_html_report", return_value="report.html"),
        patch("prat.workflow.generate_dot_graph", return_value="FDG.dot"),
        patch("prat.workflow.generate_json_report", return_value="report.json"),
    ):
        yield


class TestRunCompleteWorkflow:
    def test_symbolic_rust_request_fails_closed(self, tmp_path):
        adapter = MagicMock(
            build_system=BuildSystem.CARGO,
            coverage_tool="cargo-llvm-cov",
            source_directories=["src"],
        )

        result = run_complete_workflow(
            str(tmp_path),
            "qlog",
            output_dir=str(tmp_path / "out"),
            adapter=adapter,
            symbolic=True,
        )

        assert result.success is False
        assert "C/C++ LLVM bitcode" in (result.error_message or "")

    def test_succeeds_and_maps_the_feature(self, happy_path, tmp_path):
        result = run_complete_workflow(
            str(tmp_path), "TLS", output_dir=str(tmp_path / "out")
        )

        assert result.success is True
        assert result.checkpoint is WorkflowCheckpoint.COMPLETE
        assert result.extraction_result.total_removable_lines == 1
        assert result.extraction_result.file_line_numbers == {"src/net.c": [10]}

    def test_reports_coverage_percentage(self, happy_path, tmp_path):
        result = run_complete_workflow(
            str(tmp_path), "TLS", output_dir=str(tmp_path / "out")
        )

        assert result.coverage_percent_enabled == pytest.approx(100.0)

    def test_writes_a_checkpoint(self, happy_path, tmp_path):
        output = tmp_path / "out"
        run_complete_workflow(str(tmp_path), "TLS", output_dir=str(output))

        assert (output / "workflow_checkpoint.json").exists()

    def test_does_not_remove_unless_asked(self, happy_path, tmp_path):
        result = run_complete_workflow(
            str(tmp_path), "TLS", output_dir=str(tmp_path / "out")
        )

        assert result.removal_result is None
        assert result.verification_result is None

    def test_missing_dependencies_fails_early(self, tmp_path):
        adapter = MagicMock(
            build_system=BuildSystem.MAKE,
            coverage_tool="gcov",
            source_directories=["src"],
        )
        with (
            patch("prat.workflow.get_adapter", return_value=adapter),
            patch(
                "prat.workflow.verify_dependencies",
                return_value=EnvironmentResult(
                    success=False,
                    available_tools={},
                    missing_tools=["gcov"],
                ),
            ),
        ):
            result = run_complete_workflow(str(tmp_path), "TLS",
                                           output_dir=str(tmp_path / "out"))

        assert result.success is False
        assert result.checkpoint is WorkflowCheckpoint.START
        assert "gcov" in result.error_message

    def test_failed_enabled_compilation_stops_the_pipeline(self, tmp_path):
        failure = CompilationResult(
            success=False, binary_path=None, error_message="boom",
            compilation_time=0.0, coverage_enabled=True,
            build_system=BuildSystem.MAKE,
        )
        adapter = MagicMock(
            build_system=BuildSystem.MAKE,
            coverage_tool="gcov",
            source_directories=["src"],
        )
        with (
            patch("prat.workflow.verify_dependencies",
                  return_value=EnvironmentResult(success=True, available_tools={}, missing_tools=[])),
            patch("prat.workflow.get_adapter", return_value=adapter),
            patch("prat.workflow.compile_with_adapter", return_value=failure),
        ):
            result = run_complete_workflow(str(tmp_path), "TLS",
                                           output_dir=str(tmp_path / "out"))

        assert result.success is False
        assert result.checkpoint is WorkflowCheckpoint.COMPILE_ENABLED

    def test_failed_coverage_stops_the_pipeline(self, tmp_path):
        compilation = CompilationResult(
            success=True, binary_path=None, error_message=None,
            compilation_time=0.0, coverage_enabled=True,
            build_system=BuildSystem.MAKE,
        )
        empty = CoverageResult(
            success=False, coverage_files=[], coverage_dir="",
            missing_files=[], error_message="no gcda",
        )
        adapter = MagicMock(
            build_system=BuildSystem.MAKE,
            coverage_tool="gcov",
            source_directories=["src"],
        )
        with (
            patch("prat.workflow.verify_dependencies",
                  return_value=EnvironmentResult(success=True, available_tools={}, missing_tools=[])),
            patch("prat.workflow.get_adapter", return_value=adapter),
            patch("prat.workflow.compile_with_adapter", return_value=compilation),
            patch(
                "prat.workflow.generate_coverage_with_adapter",
                return_value=empty,
            ),
        ):
            result = run_complete_workflow(str(tmp_path), "TLS",
                                           output_dir=str(tmp_path / "out"))

        assert result.success is False
        assert result.checkpoint is WorkflowCheckpoint.COVERAGE_ENABLED

    def test_report_generation_failure_fails_the_workflow(
        self, happy_path, tmp_path
    ):
        with patch(
            "prat.workflow.generate_html_report",
            side_effect=OSError("cannot write report"),
        ):
            result = run_complete_workflow(
                str(tmp_path), "TLS", output_dir=str(tmp_path / "out")
            )

        assert result.success is False
        assert result.checkpoint is WorkflowCheckpoint.EXTRACT
        assert "cannot write report" in (result.error_message or "")


class TestRemovalAndVerification:
    def test_removal_runs_when_requested(self, happy_path, tmp_path):
        removal = RemovalResult(
            success=True, lines_removed=1, files_modified=1, files_stubbed=0
        )
        verification = VerificationResult(
            success=True, compiles=True, status=VerificationStatus.PASSED,
            total_tests_run=3, total_tests_passed=3,
        )
        with (
            patch("prat.workflow.remove_feature_code", return_value=removal) as remove,
            patch("prat.workflow.verify_correctness", return_value=verification),
        ):
            result = run_complete_workflow(
                str(tmp_path), "TLS", output_dir=str(tmp_path / "out"),
                remove=True, verify=True,
            )

        assert result.success is True
        assert result.removal_result.lines_removed == 1
        assert result.verification_result.status is VerificationStatus.PASSED
        # Shared lines must be passed through so the guard cannot absorb them.
        assert remove.call_args.kwargs["protected_lines"] == {"src/net.c": {14}}

    def test_failed_removal_fails_the_workflow(self, happy_path, tmp_path):
        removal = RemovalResult(
            success=False, lines_removed=0, files_modified=0, files_stubbed=0,
            error_message="rebuild failed", rebuild_success=False,
        )
        with patch("prat.workflow.remove_feature_code", return_value=removal):
            result = run_complete_workflow(
                str(tmp_path), "TLS", output_dir=str(tmp_path / "out"),
                remove=True,
            )

        assert result.success is False
        assert result.checkpoint is WorkflowCheckpoint.REMOVE

    def test_failed_verification_fails_the_workflow(self, happy_path, tmp_path):
        removal = RemovalResult(
            success=True, lines_removed=1, files_modified=1, files_stubbed=0
        )
        verification = VerificationResult(
            success=False, compiles=True, status=VerificationStatus.CRASHED,
            crashes=["cargo-test: SIGSEGV"], total_tests_run=1,
        )
        with (
            patch("prat.workflow.remove_feature_code", return_value=removal),
            patch("prat.workflow.verify_correctness", return_value=verification),
        ):
            result = run_complete_workflow(
                str(tmp_path), "TLS", output_dir=str(tmp_path / "out"),
                remove=True, verify=True,
            )

        assert result.success is False
        assert result.checkpoint is WorkflowCheckpoint.VERIFY

    def test_verification_skipped_when_disabled(self, happy_path, tmp_path):
        removal = RemovalResult(
            success=True, lines_removed=1, files_modified=1, files_stubbed=0
        )
        with (
            patch("prat.workflow.remove_feature_code", return_value=removal),
            patch("prat.workflow.verify_correctness") as verify,
        ):
            run_complete_workflow(
                str(tmp_path), "TLS", output_dir=str(tmp_path / "out"),
                remove=True, verify=False,
            )

        verify.assert_not_called()


class TestBaselineReuse:
    def test_reuses_a_supplied_baseline_instead_of_rebuilding(
        self, coverage_dirs, tmp_path
    ):
        """This is how batch analysis achieves Algorithm 1's n+1 builds."""
        enabled, disabled = coverage_dirs
        compilation = CompilationResult(
            success=True, binary_path=None, error_message=None,
            compilation_time=0.0, coverage_enabled=True,
            build_system=BuildSystem.MAKE,
        )
        disabled_cov = CoverageResult(
            success=True,
            coverage_files=[str(p) for p in disabled.iterdir()],
            coverage_dir=str(disabled),
            missing_files=[],
            dynamic_execution=True,
        )
        adapter = MagicMock(
            build_system=BuildSystem.MAKE,
            coverage_tool="gcov",
            source_directories=["src"],
        )

        with (
            patch("prat.workflow.verify_dependencies",
                  return_value=EnvironmentResult(success=True, available_tools={}, missing_tools=[])),
            patch("prat.workflow.get_adapter", return_value=adapter),
            patch(
                "prat.workflow.compile_with_adapter",
                return_value=compilation,
            ) as compile_mock,
            patch(
                "prat.workflow.generate_coverage_with_adapter",
                return_value=disabled_cov,
            ),
            patch("prat.workflow.generate_html_report"),
            patch("prat.workflow.generate_dot_graph"),
            patch("prat.workflow.generate_json_report"),
        ):
            result = run_complete_workflow(
                str(tmp_path), "TLS", output_dir=str(tmp_path / "out"),
                baseline_coverage_dir=str(enabled), reuse_baseline=True,
            )

        assert result.success is True
        # Only the feature-disabled build is compiled; the baseline is reused.
        assert compile_mock.call_count == 1
        assert result.extraction_result.file_line_numbers == {"src/net.c": [10]}


def test_workflow_result_excludes_mapping_from_serialization(tmp_path):
    """The mapping carries full source text and must not bloat the checkpoint."""
    result = WorkflowResult(
        success=True, project="p", feature="TLS",
        compilation_enabled=None, compilation_disabled=None,
        coverage_enabled=None, coverage_disabled=None,
        extraction_result=None, total_time=0.0,
        checkpoint=WorkflowCheckpoint.COMPLETE,
    )

    serialized = result.to_dict()

    assert "mapping" not in serialized
    assert serialized["checkpoint"] == "complete"
