"""Tests for prat.diff — the paper's side-by-side code comparison reports."""

from pathlib import Path

from prat.diff import (
    ComparisonResult,
    generate_comparison_reports,
    generate_coverage_comparison,
    generate_source_comparison,
)
from prat.mapping import map_feature

from .test_mapping import write_gcov


def build_mapping(tmp_path, enabled_lines, disabled_lines, source="src/net.c"):
    enabled = tmp_path / "on"
    disabled = tmp_path / "off"
    write_gcov(enabled, source, enabled_lines)
    write_gcov(disabled, source, disabled_lines)
    mapping = map_feature("TLS", str(enabled), str(disabled))
    return mapping, enabled, disabled


class TestCoverageComparison:
    def test_writes_one_report_per_mapped_file(self, tmp_path):
        mapping, enabled, disabled = build_mapping(
            tmp_path, {10: "4", 14: "9"}, {14: "9"}
        )

        written = generate_coverage_comparison(
            mapping, str(enabled), str(disabled), str(tmp_path / "reports")
        )

        assert len(written) == 1
        assert Path(written[0]).name == "src__net.c.coverage.html"

    def test_report_marks_mapped_lines_and_shows_both_builds(self, tmp_path):
        mapping, enabled, disabled = build_mapping(
            tmp_path, {10: "4", 14: "9"}, {14: "9"}
        )

        written = generate_coverage_comparison(
            mapping, str(enabled), str(disabled), str(tmp_path / "reports")
        )
        html = Path(written[0]).read_text()

        assert "Feature on" in html and "Feature off" in html
        assert 'class="feature"' in html
        assert "in D_f" in html

    def test_report_labels_retained_never_executed_lines(self, tmp_path):
        mapping, enabled, disabled = build_mapping(
            tmp_path, {10: "4", 12: "#####"}, {}
        )

        written = generate_coverage_comparison(
            mapping, str(enabled), str(disabled), str(tmp_path / "reports")
        )
        html = Path(written[0]).read_text()

        assert "never executed in either build" in html

    def test_escapes_source_text(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        enabled.mkdir()
        (enabled / "x.c.gcov").write_text(
            "        -:    0:Source:x.c\n        1:    1:if (a < b && c) {\n"
        )
        disabled.mkdir()
        mapping = map_feature("TLS", str(enabled), str(disabled))

        written = generate_coverage_comparison(
            mapping, str(enabled), str(disabled), str(tmp_path / "reports")
        )
        html = Path(written[0]).read_text()

        assert "&lt;" in html and "&amp;&amp;" in html

    def test_no_mapped_files_writes_nothing(self, tmp_path):
        mapping, enabled, disabled = build_mapping(tmp_path, {1: "3"}, {1: "3"})

        written = generate_coverage_comparison(
            mapping, str(enabled), str(disabled), str(tmp_path / "reports")
        )

        assert written == []


class TestSourceComparison:
    def test_pairs_original_against_debloated(self, tmp_path):
        mapping, _, _ = build_mapping(tmp_path, {2: "4"}, {})

        original = tmp_path / "orig"
        debloated = tmp_path / "new"
        for root, second_line in ((original, "removed();\n"), (debloated, "\n")):
            (root / "src").mkdir(parents=True)
            (root / "src" / "net.c").write_text(f"kept();\n{second_line}")

        written = generate_source_comparison(
            mapping, str(original), str(debloated), str(tmp_path / "reports")
        )

        html = Path(written[0]).read_text()
        assert "Original" in html and "Post-debloating" in html
        assert 'class="removed"' in html
        assert "removed();" in html

    def test_skips_files_absent_from_the_original_tree(self, tmp_path):
        mapping, _, _ = build_mapping(tmp_path, {2: "4"}, {})

        written = generate_source_comparison(
            mapping, str(tmp_path / "missing"), str(tmp_path), str(tmp_path / "r")
        )

        assert written == []


class TestGenerateComparisonReports:
    def test_writes_an_index_linking_the_reports(self, tmp_path):
        mapping, enabled, disabled = build_mapping(tmp_path, {10: "4"}, {})

        result = generate_comparison_reports(
            mapping, str(enabled), str(disabled), str(tmp_path / "out")
        )

        assert isinstance(result, ComparisonResult)
        assert result.success is True
        assert result.index_path is not None
        index = Path(result.index_path).read_text()
        assert "Code comparison reports" in index
        assert "src__net.c.coverage.html" in index

    def test_source_reports_require_both_trees(self, tmp_path):
        mapping, enabled, disabled = build_mapping(tmp_path, {10: "4"}, {})

        result = generate_comparison_reports(
            mapping, str(enabled), str(disabled), str(tmp_path / "out")
        )

        assert result.source_reports == []
        assert Path(result.index_path).read_text().count("None generated") == 1

    def test_total_reports_counts_both_kinds(self, tmp_path):
        mapping, enabled, disabled = build_mapping(tmp_path, {1: "4"}, {})
        original = tmp_path / "orig"
        (original / "src").mkdir(parents=True)
        (original / "src" / "net.c").write_text("removed();\n")
        debloated = tmp_path / "new"
        (debloated / "src").mkdir(parents=True)
        (debloated / "src" / "net.c").write_text("\n")

        result = generate_comparison_reports(
            mapping, str(enabled), str(disabled), str(tmp_path / "out"),
            original_root=str(original), debloated_root=str(debloated),
        )

        assert result.total_reports == 2
