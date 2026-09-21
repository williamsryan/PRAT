"""Tests for prat.gcov — gcov parsing and line-range merging."""

from prat.gcov import (
    format_ranges,
    load_coverage_dir,
    merge_contiguous,
    parse_gcov,
    parse_tool_function_output,
    write_function_sidecar,
)

# A gcov file exercising all three line states.
SAMPLE = """\
        -:    0:Source:src/net.c
        -:    0:Graph:net.gcno
        -:    1:#include <net.h>
        4:    2:int connect_tls(void) {
    #####:    3:    unreachable();
        -:    4:}
       12:    5:int core(void) { return 0; }
        0:    6:    explicit_zero();
"""


class TestParseGcov:
    def test_parses_source_header(self, tmp_path):
        path = tmp_path / "net.c.gcov"
        path.write_text(SAMPLE)

        gcov = parse_gcov(str(path))

        assert gcov is not None
        assert gcov.source_path == "src/net.c"

    def test_executed_lines_are_those_with_positive_counts(self, tmp_path):
        path = tmp_path / "net.c.gcov"
        path.write_text(SAMPLE)

        gcov = parse_gcov(str(path))

        assert gcov.executed == {2, 5}

    def test_hash_marker_is_never_executed_not_executed(self, tmp_path):
        """`#####` means executable but not run — it must never enter L."""
        path = tmp_path / "net.c.gcov"
        path.write_text(SAMPLE)

        gcov = parse_gcov(str(path))

        assert 3 in gcov.never_executed
        assert 3 not in gcov.executed

    def test_explicit_zero_count_is_never_executed(self, tmp_path):
        path = tmp_path / "net.c.gcov"
        path.write_text(SAMPLE)

        gcov = parse_gcov(str(path))

        assert 6 in gcov.never_executed
        assert 6 not in gcov.executed

    def test_dash_lines_are_non_executable(self, tmp_path):
        path = tmp_path / "net.c.gcov"
        path.write_text(SAMPLE)

        gcov = parse_gcov(str(path))

        # Line 4 is a bare closing brace; line 1 an include.
        assert {1, 4} <= gcov.non_executable
        assert not ({1, 4} & gcov.executable)

    def test_counts_with_asterisk_suffix_are_executed(self, tmp_path):
        path = tmp_path / "x.c.gcov"
        path.write_text("        -:    0:Source:x.c\n       7*:    1:partially();\n")

        gcov = parse_gcov(str(path))

        assert gcov.executed == {1}

    def test_line_coverage_counts_only_executable_lines(self, tmp_path):
        path = tmp_path / "net.c.gcov"
        path.write_text(SAMPLE)

        gcov = parse_gcov(str(path))

        # Executable = {2, 3, 5, 6}; executed = {2, 5}.
        assert gcov.line_coverage() == (2, 4)

    def test_header_only_file_returns_none(self, tmp_path):
        path = tmp_path / "empty.c.gcov"
        path.write_text("        -:    0:Source:empty.c\n")

        assert parse_gcov(str(path)) is None

    def test_missing_file_returns_none(self):
        assert parse_gcov("/nonexistent/x.gcov") is None


class TestFunctionCoverage:
    def test_parses_gnu_gcov_function_lines(self, tmp_path):
        path = tmp_path / "net.c.gcov"
        path.write_text(
            "        -:    0:Source:src/net.c\n"
            "function connect_tls called 4 returned 100% blocks executed 86%\n"
            "function unused_fn called 0 returned 0% blocks executed 0%\n"
            "        4:    1:int connect_tls(void) { return 0; }\n"
        )

        gcov = parse_gcov(str(path))

        assert gcov.functions == {"connect_tls": 4, "unused_fn": 0}
        assert gcov.covered_functions == {"connect_tls"}
        assert gcov.function_coverage() == (1, 2)

    def test_parses_llvm_cov_stdout_format(self):
        output = (
            "Function 'main'\n"
            "Lines executed:100.00% of 4\n"
            "\n"
            "Function 'never_run'\n"
            "Lines executed:0.00% of 2\n"
            "\n"
            "File 't.c'\n"
            "Lines executed:66.00% of 6\n"
        )

        parsed = parse_tool_function_output(output)

        assert parsed == {"t.c": {"main": 1, "never_run": 0}}

    def test_sidecar_round_trips_into_loaded_coverage(self, tmp_path):
        (tmp_path / "t.c.gcov").write_text(
            "        -:    0:Source:t.c\n        1:    1:int main(void){return 0;}\n"
        )
        write_function_sidecar(str(tmp_path), {"t.c": {"main": 1, "unused": 0}})

        loaded = load_coverage_dir(str(tmp_path))

        assert loaded["t.c"].function_coverage() == (1, 2)


class TestLoadCoverageDir:
    def test_keys_by_source_path_not_basename(self, tmp_path):
        (tmp_path / "a.gcov").write_text(
            "        -:    0:Source:av1/encoder/rdopt.c\n        1:    1:a();\n"
        )
        (tmp_path / "b.gcov").write_text(
            "        -:    0:Source:av1/decoder/rdopt.c\n        1:    1:b();\n"
        )

        loaded = load_coverage_dir(str(tmp_path))

        # Same basename, different directories: must stay distinct.
        assert set(loaded) == {"av1/encoder/rdopt.c", "av1/decoder/rdopt.c"}

    def test_unions_executed_lines_across_translation_units(self, tmp_path):
        """A header included by two TUs yields two .gcov files for one source."""
        (tmp_path / "one.gcov").write_text(
            "        -:    0:Source:inc/util.h\n"
            "        3:    1:inline int a(void){return 1;}\n"
            "    #####:    2:inline int b(void){return 2;}\n"
        )
        (tmp_path / "two.gcov").write_text(
            "        -:    0:Source:inc/util.h\n"
            "    #####:    1:inline int a(void){return 1;}\n"
            "        5:    2:inline int b(void){return 2;}\n"
        )

        loaded = load_coverage_dir(str(tmp_path))

        gcov = loaded["inc/util.h"]
        assert gcov.executed == {1, 2}
        # A line executed in one TU must not remain marked never-executed.
        assert gcov.never_executed == set()

    def test_missing_directory_is_empty(self):
        assert load_coverage_dir("/nonexistent") == {}


class TestMergeContiguous:
    def test_groups_consecutive_runs(self):
        assert merge_contiguous([12, 13, 14, 44, 91, 92]) == [(12, 14), (44, 44), (91, 92)]

    def test_single_line(self):
        assert merge_contiguous([7]) == [(7, 7)]

    def test_empty(self):
        assert merge_contiguous([]) == []

    def test_sorts_and_deduplicates(self):
        assert merge_contiguous([5, 3, 4, 3]) == [(3, 5)]

    def test_format_ranges_is_compact(self):
        assert format_ranges([12, 13, 14, 44, 91, 92]) == "12-14, 44, 91-92"

    def test_format_ranges_empty(self):
        assert format_ranges([]) == ""
