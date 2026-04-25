"""Tests for prat.batch module."""

from unittest.mock import patch

from prat.batch import (
    FeatureAnalysis,
    _build_cross_feature_map,
    run_batch_analysis,
)
from prat.discovery import Feature
from prat.extraction import ExtractionResult
from prat.workflow import WorkflowCheckpoint, WorkflowResult


def _make_feature(name, desc=None):
    return Feature(name=name, description=desc)


def _make_workflow_result(success=True, lines=100, files=None):
    if files is None:
        files = {"net.c": 60, "tls.c": 40}

    return WorkflowResult(
        success=success,
        project="test",
        feature="TEST",
        compilation_enabled=None,
        compilation_disabled=None,
        coverage_enabled=None,
        coverage_disabled=None,
        diff_result=None,
        extraction_result=ExtractionResult(
            success=success,
            file_line_counts=files,
            total_removable_lines=lines,
            file_line_numbers={},
            file_line_content={},
        ) if success else None,
        total_time=1.0,
        checkpoint=WorkflowCheckpoint.COMPLETE if success else WorkflowCheckpoint.START,
    )


class TestBuildCrossFeatureMap:
    def test_no_overlap(self):
        results = {
            "TLS": FeatureAnalysis(
                feature=_make_feature("TLS"),
                affected_files=["tls.c", "ssl.c"],
            ),
            "BRIDGE": FeatureAnalysis(
                feature=_make_feature("BRIDGE"),
                affected_files=["bridge.c"],
            ),
        }

        cmap = _build_cross_feature_map(results)

        assert len(cmap.shared_files) == 0
        assert cmap.feature_to_files["TLS"] == {"tls.c", "ssl.c"}
        assert cmap.feature_to_files["BRIDGE"] == {"bridge.c"}

    def test_shared_files_detected(self):
        results = {
            "TLS": FeatureAnalysis(
                feature=_make_feature("TLS"),
                affected_files=["net.c", "tls.c"],
            ),
            "BRIDGE": FeatureAnalysis(
                feature=_make_feature("BRIDGE"),
                affected_files=["net.c", "bridge.c"],
            ),
        }

        cmap = _build_cross_feature_map(results)

        assert len(cmap.shared_files) == 1
        pair = list(cmap.shared_files.keys())[0]
        assert "net.c" in cmap.shared_files[pair]

    def test_file_to_features_mapping(self):
        results = {
            "TLS": FeatureAnalysis(
                feature=_make_feature("TLS"),
                affected_files=["net.c"],
            ),
            "BRIDGE": FeatureAnalysis(
                feature=_make_feature("BRIDGE"),
                affected_files=["net.c"],
            ),
        }

        cmap = _build_cross_feature_map(results)

        assert cmap.file_to_features["net.c"] == {"TLS", "BRIDGE"}


class TestRunBatchAnalysis:
    @patch("prat.batch.run_complete_workflow")
    @patch("prat.batch.discover_features")
    @patch("prat.batch.get_adapter", return_value=None)
    def test_analyzes_all_features(self, mock_adapter, mock_discover, mock_workflow, tmp_path):
        mock_discover.return_value = [
            _make_feature("TLS", "TLS support"),
            _make_feature("BRIDGE", "Bridge support"),
        ]
        mock_workflow.return_value = _make_workflow_result()

        result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.features_discovered == 2
        assert result.features_analyzed == 2
        assert result.features_failed == 0
        assert mock_workflow.call_count == 2

    @patch("prat.batch.run_complete_workflow")
    @patch("prat.batch.discover_features")
    @patch("prat.batch.get_adapter", return_value=None)
    def test_skip_features(self, mock_adapter, mock_discover, mock_workflow, tmp_path):
        mock_discover.return_value = [
            _make_feature("TLS"),
            _make_feature("BRIDGE"),
            _make_feature("WEBSOCKETS"),
        ]
        mock_workflow.return_value = _make_workflow_result()

        result = run_batch_analysis(
            str(tmp_path),
            output_dir=str(tmp_path),
            skip_features=["WEBSOCKETS"],
        )

        assert result.features_discovered == 3
        assert mock_workflow.call_count == 2  # Only TLS and BRIDGE

    @patch("prat.batch.discover_features")
    @patch("prat.batch.get_adapter", return_value=None)
    def test_no_features_found(self, mock_adapter, mock_discover, tmp_path):
        mock_discover.return_value = []

        result = run_batch_analysis(str(tmp_path))

        assert result.success is False
        assert "No features" in result.error_message

    @patch("prat.batch.run_complete_workflow")
    @patch("prat.batch.discover_features")
    @patch("prat.batch.get_adapter", return_value=None)
    def test_cross_feature_map_built(self, mock_adapter, mock_discover, mock_workflow, tmp_path):
        mock_discover.return_value = [
            _make_feature("TLS"),
            _make_feature("BRIDGE"),
        ]

        # Both features affect net.c
        mock_workflow.side_effect = [
            _make_workflow_result(files={"net.c": 50, "tls.c": 30}),
            _make_workflow_result(files={"net.c": 20, "bridge.c": 40}),
        ]

        result = run_batch_analysis(str(tmp_path), output_dir=str(tmp_path))

        assert result.cross_feature_map is not None
        assert len(result.cross_feature_map.shared_files) > 0
