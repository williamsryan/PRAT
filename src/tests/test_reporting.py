"""Tests for prat.reporting module."""

import json
import os
import pytest

from prat.extraction import ExtractionResult
from prat.reporting import generate_html_report, generate_dot_graph, generate_json_report


@pytest.fixture
def sample_extraction():
    """Create a sample ExtractionResult for testing."""
    return ExtractionResult(
        success=True,
        file_line_counts={"net.c": 10, "tls.c": 25, "ssl.c": 5},
        total_removable_lines=40,
        file_line_numbers={
            "net.c": [1, 2, 3],
            "tls.c": [10, 20],
            "ssl.c": [5],
        },
        file_line_content={
            "net.c": ["ssl_init();", "ssl_connect();", "ssl_free();"],
            "tls.c": ["tls_handshake();", "tls_verify();"],
            "ssl.c": ["SSL_CTX_new();"],
        },
    )


class TestGenerateHtmlReport:
    """Tests for generate_html_report()."""

    def test_creates_html_file(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.html")
        result = generate_html_report(sample_extraction, "TLS", output)

        assert os.path.exists(result)
        assert result == output

    def test_html_contains_feature_name(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.html")
        generate_html_report(sample_extraction, "TLS", output)

        with open(output) as f:
            html = f.read()

        assert "TLS" in html

    def test_html_contains_file_names(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.html")
        generate_html_report(sample_extraction, "TLS", output)

        with open(output) as f:
            html = f.read()

        assert "net.c" in html
        assert "tls.c" in html
        assert "ssl.c" in html

    def test_html_contains_totals(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.html")
        generate_html_report(sample_extraction, "TLS", output)

        with open(output) as f:
            html = f.read()

        assert "40" in html  # total removable lines
        assert "3" in html   # file count

    def test_html_self_contained(self, tmp_path, sample_extraction):
        """Report should not reference external CDNs."""
        output = str(tmp_path / "report.html")
        generate_html_report(sample_extraction, "TLS", output)

        with open(output) as f:
            html = f.read()

        assert "cdn" not in html.lower()
        assert "maxcdn" not in html.lower()
        assert "jquery" not in html.lower()

    def test_html_is_sortable(self, tmp_path, sample_extraction):
        """Report should include sort/filter JavaScript."""
        output = str(tmp_path / "report.html")
        generate_html_report(sample_extraction, "TLS", output)

        with open(output) as f:
            html = f.read()

        assert "sortTable" in html
        assert "filter" in html


class TestGenerateDotGraph:
    """Tests for generate_dot_graph()."""

    def test_creates_dot_file(self, tmp_path, sample_extraction):
        output = str(tmp_path / "FDG.dot")
        result = generate_dot_graph(sample_extraction, "TLS", output)
        assert os.path.exists(result)

    def test_dot_is_valid_digraph(self, tmp_path, sample_extraction):
        output = str(tmp_path / "FDG.dot")
        generate_dot_graph(sample_extraction, "TLS", output)

        with open(output) as f:
            content = f.read()

        assert content.strip().startswith("digraph")
        assert "}" in content

    def test_dot_contains_file_references(self, tmp_path, sample_extraction):
        output = str(tmp_path / "FDG.dot")
        generate_dot_graph(sample_extraction, "TLS", output)

        with open(output) as f:
            content = f.read()

        assert "net.c" in content
        assert "tls.c" in content

    def test_dot_is_project_agnostic(self, tmp_path, sample_extraction):
        """DOT graph should NOT contain hardcoded project names."""
        output = str(tmp_path / "FDG.dot")
        generate_dot_graph(sample_extraction, "TLS", output)

        with open(output) as f:
            content = f.read()

        assert "MQTT" not in content
        assert "Mosquitto" not in content
        assert "Bridge Support" not in content

    def test_dot_feature_node(self, tmp_path, sample_extraction):
        output = str(tmp_path / "FDG.dot")
        generate_dot_graph(sample_extraction, "TLS", output)

        with open(output) as f:
            content = f.read()

        assert '"TLS"' in content


class TestGenerateJsonReport:
    """Tests for generate_json_report()."""

    def test_creates_json_file(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.json")
        result = generate_json_report(sample_extraction, "TLS", output)
        assert os.path.exists(result)

    def test_json_is_valid(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.json")
        generate_json_report(sample_extraction, "TLS", output)

        with open(output) as f:
            data = json.load(f)

        assert data["feature"] == "TLS"
        assert data["total_removable_lines"] == 40
        assert data["files_affected"] == 3
        assert len(data["files"]) == 3

    def test_json_files_sorted_descending(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.json")
        generate_json_report(sample_extraction, "TLS", output)

        with open(output) as f:
            data = json.load(f)

        counts = [f["removable_lines"] for f in data["files"]]
        assert counts == sorted(counts, reverse=True)

    def test_json_contains_line_numbers(self, tmp_path, sample_extraction):
        output = str(tmp_path / "report.json")
        generate_json_report(sample_extraction, "TLS", output)

        with open(output) as f:
            data = json.load(f)

        tls_entry = next(f for f in data["files"] if f["file"] == "tls.c")
        assert tls_entry["line_numbers"] == [10, 20]
