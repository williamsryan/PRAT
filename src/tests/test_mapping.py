"""Tests for prat.mapping — Algorithm 1's D_f = L_all \\ L_f.

These tests pin the paper's stated soundness property:

    "removing only those LOCs that are executed when the relevant feature is
     active, but not when the same feature is disabled. The algorithm does not
     remove LOCs that are never executed regardless of whether the feature is
     active or not."

so a regression that reintroduces never-executed lines, or lines still live with
the feature off, fails here rather than silently inflating results.
"""

from prat.gcov import load_coverage_dir
from prat.mapping import (
    coverage_percent,
    coverage_totals,
    function_percent,
    map_feature,
    map_feature_from_coverage,
    protected_lines,
)


def write_gcov(directory, source_path, lines):
    """Write a .gcov file. ``lines`` maps line number -> count field string."""
    directory.mkdir(parents=True, exist_ok=True)
    name = source_path.replace("/", "__") + ".gcov"
    body = [f"        -:    0:Source:{source_path}"]
    for number, count in sorted(lines.items()):
        body.append(f"{count:>9}:{number:>5}:code_line_{number}();")
    (directory / name).write_text("\n".join(body) + "\n")


class TestSetDifference:
    def test_maps_only_lines_executed_when_enabled(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        # Line 10: enabled-only  -> in D_f
        # Line 14: live in both  -> excluded
        write_gcov(enabled, "src/net.c", {10: "4", 14: "9"})
        write_gcov(disabled, "src/net.c", {10: "#####", 14: "9"})

        mapping = map_feature("TLS", str(enabled), str(disabled))

        assert mapping.file_line_numbers == {"src/net.c": [10]}

    def test_excludes_lines_never_executed_in_either_build(self, tmp_path):
        """The paper explicitly forbids removing these."""
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4", 12: "#####"})
        write_gcov(disabled, "src/net.c", {10: "#####", 12: "#####"})

        mapping = map_feature("TLS", str(enabled), str(disabled))

        assert mapping.total_lines == 1
        assert 12 not in mapping.files["src/net.c"].lines
        # Reported, so the soundness/completeness trade-off stays visible.
        assert mapping.excluded_never_executed == 1

    def test_excludes_lines_still_live_when_feature_disabled(self, tmp_path):
        """A line executed with the feature off is shared code, not feature code."""
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {8: "#####", 10: "4"})
        write_gcov(disabled, "src/net.c", {8: "3", 10: "#####"})

        mapping = map_feature("TLS", str(enabled), str(disabled))

        assert mapping.file_line_numbers == {"src/net.c": [10]}

    def test_three_line_classes_together(self, tmp_path):
        """Enabled-only, disabled-only and dead-in-both, in one file."""
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c",
                   {8: "#####", 10: "4", 12: "#####", 14: "9"})
        write_gcov(disabled, "src/net.c",
                   {8: "3", 10: "#####", 12: "#####", 14: "9"})

        mapping = map_feature("TLS", str(enabled), str(disabled))

        assert mapping.file_line_numbers == {"src/net.c": [10]}

    def test_file_only_in_enabled_build_contributes_executed_lines(self, tmp_path):
        """L_f is empty for such a file, so D_f is its executed line set."""
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/wsio.c", {1: "2", 2: "2", 3: "#####"})
        write_gcov(enabled, "src/core.c", {1: "5"})
        write_gcov(disabled, "src/core.c", {1: "5"})

        mapping = map_feature("WEBSOCKETS", str(enabled), str(disabled))

        assert mapping.files["src/wsio.c"].lines == [1, 2]
        assert mapping.files["src/wsio.c"].feature_only_file is True
        assert mapping.feature_only_files == ["src/wsio.c"]
        assert "src/core.c" not in mapping.files

    def test_no_difference_yields_empty_mapping(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {1: "3", 2: "3"})
        write_gcov(disabled, "src/net.c", {1: "3", 2: "3"})

        mapping = map_feature("NOOP", str(enabled), str(disabled))

        assert mapping.total_lines == 0
        assert mapping.files == {}


class TestFileMapping:
    def test_ranges_merge_contiguous_lines(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c",
                   {12: "1", 13: "1", 14: "1", 44: "1", 91: "1", 92: "1"})
        write_gcov(disabled, "src/net.c", {})

        mapping = map_feature("TLS", str(enabled), str(disabled))
        file_map = mapping.files["src/net.c"]

        assert file_map.ranges == [(12, 14), (44, 44), (91, 92)]
        assert file_map.range_label == "12-14, 44, 91-92"

    def test_shared_lines_records_l_f(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4", 14: "9"})
        write_gcov(disabled, "src/net.c", {14: "9"})

        mapping = map_feature("TLS", str(enabled), str(disabled))

        assert mapping.files["src/net.c"].shared_lines == {14}
        assert protected_lines(mapping) == {"src/net.c": {14}}

    def test_source_text_is_carried_for_mapped_lines(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4"})
        write_gcov(disabled, "src/net.c", {})

        mapping = map_feature("TLS", str(enabled), str(disabled))

        assert mapping.files["src/net.c"].source[10] == "code_line_10();"


class TestCoverageStatistics:
    def test_coverage_totals_and_percent(self, tmp_path):
        directory = tmp_path / "cov"
        write_gcov(directory, "src/a.c", {1: "1", 2: "#####", 3: "2", 4: "#####"})

        parsed = load_coverage_dir(str(directory))

        assert coverage_totals(parsed) == (2, 4)
        assert coverage_percent(parsed) == 50.0

    def test_coverage_percent_none_when_nothing_instrumented(self):
        assert coverage_percent({}) is None

    def test_function_percent_none_without_function_data(self, tmp_path):
        directory = tmp_path / "cov"
        write_gcov(directory, "src/a.c", {1: "1"})

        assert function_percent(load_coverage_dir(str(directory))) is None


class TestMapFeatureFromCoverage:
    def test_accepts_preparsed_coverage(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4"})
        write_gcov(disabled, "src/net.c", {})

        mapping = map_feature_from_coverage(
            "TLS",
            load_coverage_dir(str(enabled)),
            load_coverage_dir(str(disabled)),
        )

        assert mapping.feature == "TLS"
        assert mapping.total_lines == 1
