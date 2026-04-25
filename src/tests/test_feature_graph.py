"""Tests for prat.feature_graph module."""

import json
import os

from prat.batch import BatchResult, FeatureAnalysis
from prat.discovery import Feature
from prat.extraction import ExtractionResult
from prat.feature_graph import (
    build_feature_graph,
    build_feature_graph_from_single,
    generate_feature_graph_html,
)
from prat.workflow import WorkflowCheckpoint, WorkflowResult


def _make_extraction(files, total=None):
    if total is None:
        total = sum(files.values())
    return ExtractionResult(
        success=True,
        file_line_counts=files,
        total_removable_lines=total,
        file_line_numbers={f: list(range(c)) for f, c in files.items()},
        file_line_content={f: [f"code_{i}" for i in range(c)] for f, c in files.items()},
    )


def _make_workflow(files, total=None):
    ext = _make_extraction(files, total)
    return WorkflowResult(
        success=True, project="test", feature="TEST",
        compilation_enabled=None, compilation_disabled=None,
        coverage_enabled=None, coverage_disabled=None,
        diff_result=None, extraction_result=ext,
        total_time=1.0, checkpoint=WorkflowCheckpoint.COMPLETE,
    )


def _make_batch(feature_data):
    """feature_data: dict of feat_name -> dict of file_name -> line_count"""
    results = {}
    total = 0
    for feat_name, files in feature_data.items():
        wf = _make_workflow(files)
        fa = FeatureAnalysis(
            feature=Feature(name=feat_name),
            workflow_result=wf,
            removable_lines=sum(files.values()),
            affected_files=list(files.keys()),
        )
        results[feat_name] = fa
        total += fa.removable_lines

    return BatchResult(
        success=True, project="mosquitto",
        features_discovered=len(feature_data),
        features_analyzed=len(feature_data),
        features_failed=0,
        total_removable_lines=total,
        feature_results=results,
    )


class TestBuildFeatureGraph:
    def test_creates_feature_nodes(self):
        batch = _make_batch({
            "TLS": {"net.c": 50, "tls.c": 30},
            "BRIDGE": {"bridge.c": 40},
        })
        graph = build_feature_graph(batch)

        feat_nodes = [n for n in graph.nodes if n.node_type == "feature"]
        assert len(feat_nodes) == 2
        names = {n.label for n in feat_nodes}
        assert names == {"TLS", "BRIDGE"}

    def test_creates_file_nodes(self):
        batch = _make_batch({
            "TLS": {"net.c": 50, "tls.c": 30},
        })
        graph = build_feature_graph(batch)

        file_nodes = [n for n in graph.nodes if n.node_type == "file"]
        assert len(file_nodes) == 2

    def test_creates_edges(self):
        batch = _make_batch({
            "TLS": {"net.c": 50},
        })
        graph = build_feature_graph(batch)

        assert len(graph.edges) == 1
        assert graph.edges[0].weight == 50

    def test_shared_files_marked(self):
        batch = _make_batch({
            "TLS": {"net.c": 50, "tls.c": 30},
            "BRIDGE": {"net.c": 20, "bridge.c": 40},
        })
        graph = build_feature_graph(batch)

        net_node = next(n for n in graph.nodes if n.label == "net.c")
        assert net_node.metadata["shared"] is True
        assert net_node.metadata["feature_count"] == 2

        bridge_node = next(n for n in graph.nodes if n.label == "bridge.c")
        assert bridge_node.metadata["shared"] is False

    def test_total_lines(self):
        batch = _make_batch({
            "TLS": {"net.c": 50},
            "BRIDGE": {"bridge.c": 40},
        })
        graph = build_feature_graph(batch)
        assert graph.total_removable_lines == 90

    def test_to_dict(self):
        batch = _make_batch({"TLS": {"net.c": 50}})
        graph = build_feature_graph(batch)
        d = graph.to_dict()

        assert "nodes" in d
        assert "edges" in d
        assert d["project"] == "mosquitto"

    def test_to_json(self, tmp_path):
        batch = _make_batch({"TLS": {"net.c": 50}})
        graph = build_feature_graph(batch)

        path = str(tmp_path / "graph.json")
        graph.to_json(path)

        with open(path) as f:
            data = json.load(f)
        assert data["project"] == "mosquitto"

    def test_file_nodes_include_source_details(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)

        file_node = next(n for n in graph.nodes if n.label == "net.c")
        details = file_node.metadata["per_feature_details"]

        assert len(details) == 1
        assert details[0]["feature"] == "TLS"
        assert details[0]["line_numbers"] == [0, 1, 2]
        assert details[0]["snippet_lines"][0]["content"] == "code_0"


class TestBuildFromSingle:
    def test_single_feature(self):
        ext = _make_extraction({"net.c": 50, "tls.c": 30})
        graph = build_feature_graph_from_single(ext, "TLS", "mosquitto")

        assert len(graph.features) == 1
        assert graph.features[0] == "TLS"
        assert len(graph.nodes) == 3  # 1 feature + 2 files
        assert len(graph.edges) == 2


class TestGenerateHtml:
    def test_creates_html_file(self, tmp_path):
        batch = _make_batch({
            "TLS": {"net.c": 50, "tls.c": 30},
            "BRIDGE": {"net.c": 20, "bridge.c": 40},
        })
        graph = build_feature_graph(batch)

        path = str(tmp_path / "feature_graph.html")
        result = generate_feature_graph_html(graph, path)

        assert os.path.exists(result)

    def test_html_contains_d3(self, tmp_path):
        batch = _make_batch({"TLS": {"net.c": 50}})
        graph = build_feature_graph(batch)

        path = str(tmp_path / "feature_graph.html")
        generate_feature_graph_html(graph, path)

        with open(path) as f:
            html = f.read()
        assert "d3.js" in html or "d3@7" in html

    def test_html_contains_graph_data(self, tmp_path):
        batch = _make_batch({"TLS": {"net.c": 50}})
        graph = build_feature_graph(batch)

        path = str(tmp_path / "feature_graph.html")
        generate_feature_graph_html(graph, path)

        with open(path) as f:
            html = f.read()
        assert "GRAPH_DATA" in html
        assert "net.c" in html
        assert "TLS" in html

    def test_html_self_contained(self, tmp_path):
        """No external CSS CDNs (only D3 from CDN, which is acceptable)."""
        batch = _make_batch({"TLS": {"net.c": 50}})
        graph = build_feature_graph(batch)

        path = str(tmp_path / "feature_graph.html")
        generate_feature_graph_html(graph, path)

        with open(path) as f:
            html = f.read()
        assert "bootstrap" not in html.lower()
        assert "jquery" not in html.lower()

    def test_html_contains_inline_source_ui(self, tmp_path):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)

        path = str(tmp_path / "feature_graph.html")
        generate_feature_graph_html(graph, path)

        with open(path) as f:
            html = f.read()

        assert "Source LoC" in html
        assert "Interactive removal map" in html
        assert "light-mode analysis workspace" in html
