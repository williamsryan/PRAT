"""Tests for prat.extraction — packaging D_f for reporting and removal."""

from prat.extraction import ExtractionResult, extract_features, extract_from_mapping
from prat.mapping import map_feature

from .test_mapping import write_gcov


class TestExtractFeatures:
    def test_reports_mapped_lines(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4", 11: "4", 14: "9"})
        write_gcov(disabled, "src/net.c", {14: "9"})

        result = extract_features(str(enabled), str(disabled), "TLS")

        assert result.success is True
        assert result.total_removable_lines == 2
        assert result.file_line_counts == {"src/net.c": 2}
        assert result.file_line_numbers == {"src/net.c": [10, 11]}

    def test_never_executed_lines_are_reported_not_removed(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4", 12: "#####"})
        write_gcov(disabled, "src/net.c", {})

        result = extract_features(str(enabled), str(disabled), "TLS")

        assert result.total_removable_lines == 1
        assert result.excluded_never_executed == 1

    def test_partitions_dedicated_feature_files(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/wsio.c", {1: "2", 2: "2"})
        write_gcov(enabled, "src/net.c", {10: "1", 14: "9"})
        write_gcov(disabled, "src/net.c", {14: "9"})

        result = extract_features(str(enabled), str(disabled), "WEBSOCKETS")

        assert result.total_removable_lines == 3
        assert result.feature_only_removable_lines == 2
        assert result.interleaved_removable_lines == 1
        assert result.feature_only_source_paths == ["src/wsio.c"]

    def test_total_feature_lines_is_an_alias_not_a_larger_number(self, tmp_path):
        """Interleaved and dedicated lines partition one set; they do not sum twice."""
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/wsio.c", {1: "2"})
        write_gcov(enabled, "src/net.c", {10: "1", 14: "9"})
        write_gcov(disabled, "src/net.c", {14: "9"})

        result = extract_features(str(enabled), str(disabled), "WEBSOCKETS")

        assert result.total_feature_lines == result.total_removable_lines == 2

    def test_records_contiguous_ranges(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {12: "1", 13: "1", 44: "1"})
        write_gcov(disabled, "src/net.c", {})

        result = extract_features(str(enabled), str(disabled), "TLS")

        assert result.file_line_ranges == {"src/net.c": [(12, 13), (44, 44)]}

    def test_no_difference_is_a_valid_zero_result(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {1: "3"})
        write_gcov(disabled, "src/net.c", {1: "3"})

        result = extract_features(str(enabled), str(disabled), "NOOP")

        assert result.success is True
        assert result.total_removable_lines == 0

    def test_missing_enabled_dir_is_an_error(self, tmp_path):
        result = extract_features(str(tmp_path / "nope"), str(tmp_path), "TLS")

        assert result.success is False
        assert "does not exist" in (result.error_message or "")

    def test_unparseable_coverage_is_an_error(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        enabled.mkdir()
        disabled.mkdir()

        result = extract_features(str(enabled), str(disabled), "TLS")

        assert result.success is False
        assert "No parseable coverage" in (result.error_message or "")

    def test_can_explicitly_skip_idl_generated_translation_units(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "dds/TopicTypeSupportImpl.cpp", {1: "1"})
        write_gcov(enabled, "dds/Handwritten.cpp", {1: "1"})
        write_gcov(disabled, "dds/Handwritten.cpp", {})

        result = extract_features(
            str(enabled),
            str(disabled),
            "SECURITY",
            skip_generated_idl=True,
        )

        assert "dds/TopicTypeSupportImpl.cpp" not in result.file_line_counts
        assert "dds/Handwritten.cpp" in result.file_line_counts

    def test_keeps_idl_files_by_default(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "dds/TopicTypeSupportImpl.cpp", {1: "1"})
        write_gcov(disabled, "dds/other.cpp", {1: "1"})

        result = extract_features(str(enabled), str(disabled), "SECURITY")

        assert "dds/TopicTypeSupportImpl.cpp" in result.file_line_counts


class TestExtractFromMapping:
    def test_builds_result_from_a_mapping(self, tmp_path):
        enabled = tmp_path / "on"
        disabled = tmp_path / "off"
        write_gcov(enabled, "src/net.c", {10: "4"})
        write_gcov(disabled, "src/net.c", {})

        mapping = map_feature("TLS", str(enabled), str(disabled))
        result = extract_from_mapping(mapping)

        assert isinstance(result, ExtractionResult)
        assert result.total_removable_lines == 1
        assert result.file_line_content == {"src/net.c": ["code_line_10();"]}
