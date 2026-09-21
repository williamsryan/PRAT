"""Tests for prat.feature_graph — the paper's three-tier feature-graph DAG."""

import json
from pathlib import Path

import pytest

from prat.batch import BatchResult, FeatureAnalysis
from prat.discovery import Feature
from prat.extraction import ExtractionResult
from prat.feature_graph import (
    GraphEdge,
    GraphValidationError,
    _validate_graph,
    build_feature_graph,
    build_feature_graph_from_single,
    generate_feature_graph_html,
)
from prat.gcov import merge_contiguous
from prat.mapping import FeatureMapping


def _make_extraction(files, total=None, line_numbers=None):
    """files: file -> line count. line_numbers optionally overrides the lines."""
    if total is None:
        total = sum(files.values())

    numbers = line_numbers or {
        name: list(range(1, count + 1)) for name, count in files.items()
    }
    return ExtractionResult(
        success=True,
        file_line_counts=files,
        total_removable_lines=total,
        file_line_numbers=numbers,
        file_line_content={
            name: [f"code_{i}" for i in numbers[name]] for name in files
        },
        file_line_ranges={name: merge_contiguous(numbers[name]) for name in files},
    )


def _make_batch(feature_data, line_numbers=None):
    """feature_data: feature name -> {file name -> line count}."""
    results = {}
    total = 0
    for feature_name, files in feature_data.items():
        extraction = _make_extraction(
            files, line_numbers=(line_numbers or {}).get(feature_name)
        )
        analysis = FeatureAnalysis(
            feature=Feature(name=feature_name, raw_name=feature_name),
            mapping=FeatureMapping(feature=feature_name),
            extraction=extraction,
            removable_lines=sum(files.values()),
            affected_files=list(files),
        )
        results[feature_name] = analysis
        total += analysis.removable_lines

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

    def test_creates_feature_to_file_edges(self):
        batch = _make_batch({
            "TLS": {"net.c": 50},
        })
        graph = build_feature_graph(batch)

        feature_edges = [
            e for e in graph.edges
            if e.source.startswith("feat_") and e.target.startswith("file_")
        ]
        assert len(feature_edges) == 1
        assert feature_edges[0].weight == 50

    def test_creates_the_loc_leaf_tier(self):
        """Paper: leaves are sets of lines within source files."""
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)

        loc_nodes = [n for n in graph.nodes if n.node_type == "loc"]
        assert len(loc_nodes) == 1  # lines 1-3 are contiguous: one node
        assert loc_nodes[0].metadata["start_line"] == 1
        assert loc_nodes[0].metadata["end_line"] == 3
        assert loc_nodes[0].metadata["line_count"] == 3

    def test_creates_file_to_loc_edges(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)

        loc_edges = [
            e for e in graph.edges
            if e.source.startswith("file_") and e.target.startswith("loc_")
        ]
        assert len(loc_edges) == 1
        assert loc_edges[0].weight == 3

    def test_merges_contiguous_lines_into_one_leaf(self):
        """Paper: "contiguous lines of code are merged in a single node"."""
        batch = _make_batch(
            {"TLS": {"net.c": 6}},
            line_numbers={"TLS": {"net.c": [12, 13, 14, 44, 91, 92]}},
        )
        graph = build_feature_graph(batch)

        loc_nodes = [n for n in graph.nodes if n.node_type == "loc"]
        spans = sorted(
            (n.metadata["start_line"], n.metadata["end_line"]) for n in loc_nodes
        )
        assert spans == [(12, 14), (44, 44), (91, 92)]

    def test_loc_tier_can_be_omitted(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch, include_loc_nodes=False)

        assert not [n for n in graph.nodes if n.node_type == "loc"]

    def test_loc_nodes_can_be_capped_per_file(self):
        batch = _make_batch(
            {"TLS": {"net.c": 4}},
            line_numbers={"TLS": {"net.c": [1, 5, 9, 13]}},
        )
        graph = build_feature_graph(batch, max_loc_nodes_per_file=2)

        assert len([n for n in graph.nodes if n.node_type == "loc"]) == 2

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
        assert details[0]["line_numbers"] == [1, 2, 3]
        assert details[0]["snippet_lines"][0]["content"] == "code_1"

    def test_line_number_preview_is_a_range_list_not_a_span(self):
        """A first-last span would misleadingly bridge the gaps between runs."""
        batch = _make_batch(
            {"TLS": {"net.c": 6}},
            line_numbers={"TLS": {"net.c": [12, 13, 14, 44, 91, 92]}},
        )
        graph = build_feature_graph(batch)

        file_node = next(n for n in graph.nodes if n.label == "net.c")
        preview = file_node.metadata["per_feature_details"][0]["line_number_preview"]
        assert preview == "12-14, 44, 91-92"


class TestBuildFromSingle:
    def test_single_feature(self):
        ext = _make_extraction({"net.c": 50, "tls.c": 30})
        graph = build_feature_graph_from_single(ext, "TLS", "mosquitto")

        assert graph.features == ["TLS"]
        # 1 feature root + 2 file nodes + 1 contiguous LOC leaf per file.
        assert len([n for n in graph.nodes if n.node_type == "feature"]) == 1
        assert len([n for n in graph.nodes if n.node_type == "file"]) == 2
        assert len([n for n in graph.nodes if n.node_type == "loc"]) == 2
        assert len(graph.edges) == 4


class TestGenerateHtml:
    def test_creates_html_file(self, tmp_path):
        batch = _make_batch({
            "TLS": {"net.c": 50, "tls.c": 30},
            "BRIDGE": {"net.c": 20, "bridge.c": 40},
        })
        graph = build_feature_graph(batch)

        path = str(tmp_path / "feature_graph.html")
        result = generate_feature_graph_html(graph, path)

        assert Path(result).exists()

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


class TestGraphInvariants:
    """The paper defines a feature graph as a DAG with an explicit tier order."""

    def test_built_graph_validates(self):
        batch = _make_batch({
            "TLS": {"net.c": 50, "tls.c": 30},
            "BRIDGE": {"net.c": 20, "bridge.c": 40},
        })
        graph = build_feature_graph(batch)

        _validate_graph(graph)  # must not raise

    def test_node_ids_are_unique(self):
        batch = _make_batch({
            "TLS": {"net.c": 5},
            "BRIDGE": {"net.c": 5},
        })
        graph = build_feature_graph(batch)

        ids = [n.id for n in graph.nodes]
        assert len(ids) == len(set(ids))

    def test_a_run_shared_by_two_features_is_one_vertex(self):
        """V is a set: the same line range must not appear twice."""
        batch = _make_batch(
            {"TLS": {"net.c": 3}, "BRIDGE": {"net.c": 3}},
            line_numbers={
                "TLS": {"net.c": [1, 2, 3]},
                "BRIDGE": {"net.c": [1, 2, 3]},
            },
        )
        graph = build_feature_graph(batch)

        loc_nodes = [n for n in graph.nodes if n.node_type == "loc"]
        assert len(loc_nodes) == 1
        assert sorted(loc_nodes[0].metadata["features"]) == ["BRIDGE", "TLS"]

    def test_tiers_run_feature_then_file_then_loc(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)

        tier = {"feature": 0, "file": 1, "loc": 2}
        by_id = {n.id: tier[n.node_type] for n in graph.nodes}
        for edge in graph.edges:
            assert by_id[edge.target] == by_id[edge.source] + 1

    def test_features_are_roots_and_loc_nodes_are_leaves(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)

        targets = {e.target for e in graph.edges}
        sources = {e.source for e in graph.edges}
        for node in graph.nodes:
            if node.node_type == "feature":
                assert node.id not in targets
            if node.node_type == "loc":
                assert node.id not in sources

    def test_validator_rejects_a_back_edge(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)
        loc = next(n for n in graph.nodes if n.node_type == "loc")
        graph.edges.append(GraphEdge(source=loc.id, target="feat_TLS"))

        with pytest.raises(GraphValidationError):
            _validate_graph(graph)

    def test_validator_rejects_a_self_loop(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)
        graph.edges.append(GraphEdge(source="feat_TLS", target="feat_TLS"))

        with pytest.raises(GraphValidationError, match="self-loop"):
            _validate_graph(graph)

    def test_validator_rejects_a_dangling_edge(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)
        graph.edges.append(GraphEdge(source="feat_TLS", target="file_absent.c"))

        with pytest.raises(GraphValidationError, match="not a vertex"):
            _validate_graph(graph)

    def test_validator_rejects_duplicate_ids(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        graph = build_feature_graph(batch)
        graph.nodes.append(graph.nodes[0])

        with pytest.raises(GraphValidationError, match="duplicate"):
            _validate_graph(graph)

    def test_discarded_features_are_not_graphed(self):
        batch = _make_batch({"TLS": {"net.c": 3}})
        broken = FeatureAnalysis(feature=Feature(name="BROKEN", raw_name="BROKEN"))
        broken.discarded_reason = "compilation failed"
        batch.feature_results["BROKEN"] = broken

        graph = build_feature_graph(batch)

        assert graph.features == ["TLS"]
        assert not [n for n in graph.nodes if n.label == "BROKEN"]
