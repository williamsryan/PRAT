"""Tests for prat.removal — the balance guard and the build gate."""

import shutil
import subprocess

import pytest

from prat.extraction import ExtractionResult
from prat.removal import (
    RemovalResult,
    compute_line_deltas,
    plan_removal,
    remove_feature_code,
    restore_from_backup,
)

GUARDED_SOURCE = """\
#include <stdio.h>
void do_more(void);
void feature_fn(int x) {
    if (x > 0) {
        printf("a");
        do_more();
    }
    return;
}
int main(void) { feature_fn(0); return 0; }
"""


def make_extraction(file_line_numbers, feature_only=None):
    counts = {name: len(lines) for name, lines in file_line_numbers.items()}
    return ExtractionResult(
        success=True,
        file_line_counts=counts,
        total_removable_lines=sum(counts.values()),
        file_line_numbers=file_line_numbers,
        file_line_content={
            name: [""] * len(lines) for name, lines in file_line_numbers.items()
        },
        feature_only_source_paths=list(feature_only or ()),
    )


class TestComputeLineDeltas:
    def test_counts_net_bracket_delta(self):
        assert compute_line_deltas(["if (x) {\n", "}\n"]) == [1, -1]

    def test_ignores_braces_in_strings(self):
        assert compute_line_deltas(['printf("{");\n']) == [0]

    def test_ignores_braces_in_char_literals(self):
        assert compute_line_deltas(["char c = '{';\n"]) == [0]

    def test_ignores_line_comments(self):
        assert compute_line_deltas(["int x; // }\n"]) == [0]

    def test_ignores_block_comments_across_lines(self):
        lines = ["/* {\n", "   }\n", "*/ int y;\n"]
        assert compute_line_deltas(lines) == [0, 0, 0]

    def test_handles_escaped_quote_in_string(self):
        assert compute_line_deltas(['puts("a\\"{");\n']) == [0]


class TestPlanRemoval:
    def test_absorbs_closing_brace_to_stay_balanced(self):
        """gcov never marks `}` executable, so the guard must pull it in."""
        lines = GUARDED_SOURCE.splitlines(keepends=True)

        approved, skipped, absorbed = plan_removal(lines, {4, 5, 6})

        assert approved == {4, 5, 6, 7}  # line 7 is the closing brace
        assert skipped == []
        assert absorbed == 1

    def test_balanced_run_needs_no_absorption(self):
        lines = ["a();\n", "b();\n", "c();\n"]

        approved, skipped, absorbed = plan_removal(lines, {2})

        assert approved == {2}
        assert absorbed == 0

    def test_declines_a_run_it_cannot_balance(self):
        """An unclosed brace followed by live code must not be removed."""
        lines = ["if (x) {\n", "    keep_me();\n", "}\n"]

        approved, skipped, absorbed = plan_removal(
            lines, {1}, protected={2, 3}
        )

        assert approved == set()
        assert skipped == [(1, 1)]

    def test_never_removes_protected_lines(self):
        lines = ["a();\n", "b();\n", "c();\n"]

        approved, _, _ = plan_removal(lines, {1, 2, 3}, protected={2})

        assert approved == {1, 3}

    def test_ignores_out_of_range_line_numbers(self):
        lines = ["a();\n"]

        approved, _, _ = plan_removal(lines, {1, 99})

        assert approved == {1}

    def test_bridges_a_gap_that_is_only_an_opening_brace(self):
        """gcov puts a function's entry block on its signature line, and the
        opening brace on the next line gets `-:`. Treating those as two separate
        balanced runs would remove the signature and orphan the body."""
        lines = [
            "int feature_helper(int value)\n",   # 1 — in D_f (entry block)
            "{\n",                               # 2 — "-:" in gcov
            "    return value * 2;\n",           # 3 — in D_f
            "}\n",                               # 4 — "-:" in gcov
            "int keep(void) { return 0; }\n",    # 5 — must survive
        ]

        approved, skipped, absorbed = plan_removal(lines, {1, 3})

        # The whole function goes, or none of it would.
        assert approved == {1, 2, 3, 4}
        assert skipped == []
        assert absorbed == 2  # the two braces
        assert 5 not in approved

    def test_does_not_bridge_across_live_code(self):
        lines = [
            "feature_a();\n",   # 1 — in D_f
            "shared();\n",      # 2 — live with the feature off
            "feature_b();\n",   # 3 — in D_f
        ]

        approved, _skipped, _absorbed = plan_removal(
            lines, {1, 3}, protected={2}
        )

        assert approved == {1, 3}

    def test_does_not_bridge_across_a_protected_brace(self):
        lines = ["if (x) {\n", "}\n", "b();\n"]

        approved, _skipped, _absorbed = plan_removal(
            lines, {1, 3}, protected={2}
        )

        assert 2 not in approved

    def test_absorbs_preceding_opener_for_unmatched_closer(self):
        lines = ["{\n", "    body();\n", "}\n"]

        approved, skipped, absorbed = plan_removal(lines, {2, 3})

        assert approved == {1, 2, 3}
        assert skipped == []
        assert absorbed == 1


@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler available")
class TestGuardPreservesCompilation:
    def test_guarded_removal_still_compiles(self, tmp_path):
        source = tmp_path / "guarded.c"
        source.write_text(GUARDED_SOURCE)

        lines = GUARDED_SOURCE.splitlines(keepends=True)
        approved, _, _ = plan_removal(lines, {4, 5, 6})
        for number in approved:
            lines[number - 1] = "\n"
        source.write_text("".join(lines))

        proc = subprocess.run(
            ["cc", "-fsyntax-only", str(source)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr

    def test_unguarded_removal_breaks_compilation(self, tmp_path):
        """Establishes that the guard is load-bearing, not decorative."""
        source = tmp_path / "unguarded.c"
        lines = GUARDED_SOURCE.splitlines(keepends=True)
        for number in (4, 5, 6):
            lines[number - 1] = "\n"
        source.write_text("".join(lines))

        proc = subprocess.run(
            ["cc", "-fsyntax-only", str(source)],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0


class TestRemoveFeatureCode:
    def test_blanks_mapped_lines_and_preserves_numbering(self, tmp_path):
        source = tmp_path / "net.c"
        source.write_text("one();\ntwo();\nthree();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [2]}),
            str(tmp_path),
            "TLS",
            rebuild=False,
        )

        assert result.success is True
        assert result.lines_removed == 1
        # Line count unchanged, so stored line numbers stay valid.
        assert source.read_text() == "one();\n\nthree();\n"

    def test_creates_a_backup_by_default(self, tmp_path):
        (tmp_path / "net.c").write_text("one();\ntwo();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=False,
        )

        assert result.backup_dir is not None
        assert (tmp_path / "_backup_before_remove_TLS" / "net.c").read_text() == (
            "one();\ntwo();\n"
        )

    def test_restore_from_backup_reverts_the_change(self, tmp_path):
        source = tmp_path / "net.c"
        source.write_text("one();\ntwo();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=False,
        )
        assert source.read_text() != "one();\ntwo();\n"

        assert restore_from_backup(result.backup_dir, str(tmp_path)) is True
        assert source.read_text() == "one();\ntwo();\n"

    def test_stubs_dedicated_feature_files(self, tmp_path):
        (tmp_path / "wsio.c").write_text("int ws(void) { return 1; }\n")

        result = remove_feature_code(
            make_extraction({"wsio.c": [1]}, feature_only=["wsio.c"]),
            str(tmp_path),
            "WEBSOCKETS",
            rebuild=False,
            stub_feature_only_files=True,
            require_complete=False,
        )

        assert result.files_stubbed == 1
        assert "removed by PRAT" in (tmp_path / "wsio.c").read_text()

    def test_reports_runs_the_guard_declined(self, tmp_path):
        (tmp_path / "net.c").write_text("if (x) {\n    keep();\n}\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            protected_lines={"net.c": {2, 3}},
            rebuild=False,
        )

        assert result.lines_removed == 0
        assert result.skipped_unbalanced == {"net.c": [(1, 1)]}
        assert result.skipped_line_count == 1

    def test_missing_source_file_fails_exact_removal(self, tmp_path):
        result = remove_feature_code(
            make_extraction({"absent.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=False,
        )

        assert result.success is False
        assert result.lines_removed == 0
        assert result.missing_source_files == ["absent.c"]

    def test_dedicated_file_defaults_to_exact_mapped_lines(self, tmp_path):
        source = tmp_path / "wsio.c"
        source.write_text("mapped();\nnever_executed();\n")

        result = remove_feature_code(
            make_extraction({"wsio.c": [1]}, feature_only=["wsio.c"]),
            str(tmp_path),
            "WEBSOCKETS",
            rebuild=False,
        )

        assert result.success is True
        assert result.files_stubbed == 0
        assert source.read_text() == "\nnever_executed();\n"


class TestBuildGate:
    def test_failed_rebuild_fails_the_removal(self, tmp_path):
        """The paper relies on a broken build stopping bad removals."""
        (tmp_path / "net.c").write_text("one();\ntwo();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=True,
            build_command=["false"],
        )

        assert result.success is False
        assert result.rebuild_success is False
        assert "Rebuild failed" in (result.error_message or "")

    def test_failed_rebuild_restores_the_tree(self, tmp_path):
        source = tmp_path / "net.c"
        source.write_text("one();\ntwo();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=True,
            build_command=["false"],
        )

        assert result.restored is True
        assert source.read_text() == "one();\ntwo();\n"

    def test_successful_rebuild_keeps_the_removal(self, tmp_path):
        source = tmp_path / "net.c"
        source.write_text("one();\ntwo();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=True,
            build_command=["true"],
        )

        assert result.success is True
        assert result.rebuild_success is True
        assert result.restored is False
        assert source.read_text() == "\ntwo();\n"

    def test_restore_puts_nested_files_back_with_a_relative_project_path(
        self, tmp_path, monkeypatch
    ):
        """CMake builds make gcov record absolute source paths, and the CLI is
        usually run with a relative project path. The backup must mirror the
        tree so the restore lands on lib/net.c, not on a new net.c at the
        project root."""
        project = tmp_path / "proj"
        (project / "lib").mkdir(parents=True)
        source = project / "lib" / "net.c"
        source.write_text("one();\ntwo();\n")
        monkeypatch.chdir(tmp_path)

        result = remove_feature_code(
            make_extraction({str(source.resolve()): [1]}),
            "proj",
            "TLS",
            rebuild=True,
            build_command=["false"],
        )

        assert result.restored is True
        assert source.read_text() == "one();\ntwo();\n"
        assert not (project / "net.c").exists()
        assert (project / "_backup_before_remove_TLS" / "lib" / "net.c").exists()

    def test_sources_outside_the_project_are_never_modified(self, tmp_path):
        """An executed inline function in a system header can land in D_f;
        removal must leave the toolchain alone and say so."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "net.c").write_text("one();\ntwo();\n")
        header = tmp_path / "usr" / "include" / "x509v3.h"
        header.parent.mkdir(parents=True)
        header.write_text("inline();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1], str(header.resolve()): [1]}),
            str(project),
            "TLS",
            rebuild=False,
        )

        assert header.read_text() == "inline();\n"
        assert result.out_of_tree_sources == [str(header.resolve())]
        assert result.success is False
        assert "outside the project tree" in (result.error_message or "")
        assert not (project / "_backup_before_remove_TLS" / "x509v3.h").exists()

    def test_no_restore_when_disabled(self, tmp_path):
        source = tmp_path / "net.c"
        source.write_text("one();\ntwo();\n")

        result = remove_feature_code(
            make_extraction({"net.c": [1]}),
            str(tmp_path),
            "TLS",
            rebuild=True,
            build_command=["false"],
            restore_on_build_failure=False,
        )

        assert result.success is False
        assert result.restored is False
        assert source.read_text() == "\ntwo();\n"


def test_removal_result_defaults():
    result = RemovalResult(
        success=True, lines_removed=0, files_modified=0, files_stubbed=0
    )
    assert result.skipped_line_count == 0
    assert result.absorbed_structural == 0
