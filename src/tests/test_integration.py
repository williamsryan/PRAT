"""End-to-end integration test on a real C project.

Compiles a small Make-based program twice (feature on, feature off) with real
coverage instrumentation, runs it, invokes gcov, computes D_f, removes the mapped
lines and rebuilds. Everything that the unit tests stub out — the compiler, gcov,
the coverage file format, the balance guard against a real parser — runs for real
here.

The program is deliberately shaped like the case the paper is about: the feature
has code guarded by ``#ifdef`` (which a build flag does remove) *and* interleaved
code in a shared file that the flag leaves behind but that only executes when the
feature is on. It also contains a compiled-but-never-executed function, which
Algorithm 1 must decline to remove.

Skipped when no C toolchain or gcov-compatible tool is available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from prat.adapters.base import ProjectAdapter
from prat.batch import run_batch_analysis
from prat.compilation import BuildSystem
from prat.extraction import extract_from_mapping
from prat.gcov import (
    load_coverage_dir,
    parse_tool_function_output,
    write_function_sidecar,
)
from prat.mapping import map_feature_from_coverage, protected_lines
from prat.removal import remove_feature_code

CC = shutil.which("cc") or shutil.which("gcc")


def _gcov_tool() -> list[str] | None:
    """A command that turns .gcda/.gcno into .gcov, or None if none works."""
    if shutil.which("gcov"):
        return ["gcov"]
    llvm = shutil.which("llvm-cov")
    if llvm:
        return [llvm, "gcov"]
    return None


GCOV = _gcov_tool()

pytestmark = pytest.mark.skipif(
    CC is None or GCOV is None,
    reason="needs a C compiler and gcov (or llvm-cov)",
)

# --- The program under analysis --------------------------------------------

MAIN_C = """\
#include <stdio.h>
#include "feature.h"

int shared_counter = 0;

/* Interleaved feature code: no #ifdef guard, so toggling the build flag does
   NOT remove it, but it only ever executes when the feature is active. This is
   the code the paper's differential analysis is designed to find. */
int feature_helper(int value)
{
    shared_counter += 1;
    return value * 2;
}

/* Compiled in both configurations and never executed. Algorithm 1 must leave
   this alone: "does not remove LOCs that are never executed regardless of
   whether the feature is active or not". */
int never_runs(int value)
{
    return value + 999;
}

int core_work(int value)
{
    shared_counter += 1;
    return value + 1;
}

int main(void)
{
    int total = core_work(1);
#ifdef WITH_MYFEATURE
    total += feature_enabled_entry(2);
    total += feature_helper(3);
#endif
    printf("total=%d counter=%d\\n", total, shared_counter);
    return 0;
}
"""

FEATURE_H = """\
#ifndef FEATURE_H
#define FEATURE_H
int feature_helper(int value);
int core_work(int value);
int never_runs(int value);
#ifdef WITH_MYFEATURE
int feature_enabled_entry(int value);
#endif
#endif
"""

FEATURE_C = """\
#include "feature.h"

/* A file that only participates in the build when the feature is enabled. */
int feature_enabled_entry(int value)
{
    return feature_helper(value) + 1;
}
"""

MAKEFILE = """\
CC ?= cc
COVERAGE ?= --coverage
WITH_MYFEATURE ?= yes

SOURCES := main.c
CFLAGS := -O0 -g $(COVERAGE)

ifeq ($(WITH_MYFEATURE),yes)
CFLAGS += -DWITH_MYFEATURE
SOURCES += feature.c
endif

all: app

app: $(SOURCES)
\t$(CC) $(CFLAGS) -o app $(SOURCES)

clean:
\trm -f app *.gcda *.gcno *.gcov

.PHONY: all clean
"""


def _write_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.c").write_text(MAIN_C)
    (root / "feature.h").write_text(FEATURE_H)
    (root / "feature.c").write_text(FEATURE_C)
    (root / "Makefile").write_text(MAKEFILE)


BATCH_MAIN_C = """\
#include <stdio.h>

int alpha(void)
{
    puts("alpha");
    return 1;
}

int beta(void)
{
    puts("beta");
    return 2;
}

int main(void)
{
    int total = 0;
#ifdef WITH_ALPHA
    total += alpha();
#endif
#ifdef WITH_BETA
    total += beta();
#endif
    printf("total=%d\\n", total);
    return 0;
}
"""

BATCH_MAKEFILE = """\
CC ?= cc
CFLAGS ?= --coverage -O0
WITH_ALPHA ?= no
WITH_BETA ?= no

DEFS :=
ifeq ($(WITH_ALPHA),yes)
DEFS += -DWITH_ALPHA
endif
ifeq ($(WITH_BETA),yes)
DEFS += -DWITH_BETA
endif

all: src/app

src/app: src/main.c
\tcd src && $(CC) $(CFLAGS) $(DEFS) -o app main.c

test: src/app
\t./src/app

clean:
\trm -f src/app src/*.gcda src/*.gcno src/*.gcov

.PHONY: all test clean
"""


class BatchFixtureAdapter(ProjectAdapter):
    """Real compiler/gcov adapter for the Algorithm 1 integration fixture."""

    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.MAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov" if shutil.which("gcov") else "llvm-cov"

    @property
    def source_directories(self) -> list[str]:
        return ["src"]

    def normalize_feature_name(self, raw_option: str) -> str:
        return raw_option.removeprefix("WITH_")

    def get_compile_command(
        self,
        feature: str,
        enabled: bool,
        with_coverage: bool = True,
    ) -> list[str]:
        coverage = "--coverage -O0" if with_coverage else "-O0"
        return [
            "make",
            f"CC={CC}",
            f"CFLAGS={coverage}",
            self.format_feature_flag(feature, enabled),
        ]

    def get_clean_command(self) -> list[str]:
        return ["make", "clean"]

    def get_test_command(self) -> list[str] | None:
        return ["make", "test"]

    def get_execution_commands(
        self, feature: str, enabled: bool
    ) -> list[list[str]]:
        return [["./src/app"]]

    def get_binary_path(self) -> str | None:
        return str(self.project_path / "src" / "app")

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"WITH_{feature}={'yes' if enabled else 'no'}"


def _build_run_and_cover(root: Path, enabled: bool, coverage_dir: Path) -> None:
    """Build with the feature on/off, run the binary, and collect .gcov files."""
    subprocess.run(["make", "clean"], cwd=root, capture_output=True, check=False)

    build = subprocess.run(
        ["make", f"WITH_MYFEATURE={'yes' if enabled else 'no'}", f"CC={CC}"],
        cwd=root, capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stderr

    run = subprocess.run(["./app"], cwd=root, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr

    # Invoke gcov on the .gcda profile data the run above produced. Passing the
    # source name instead works with GNU gcov but not with the llvm-cov-backed
    # gcov shipped on macOS, so the profile files are the portable input.
    profiles = sorted(p.name for p in root.glob("*.gcda"))
    assert profiles, "the run produced no .gcda profile data"

    proc = subprocess.run(
        [*GCOV, "-f", *profiles],
        cwd=root, capture_output=True, text=True,
    )

    coverage_dir.mkdir(parents=True, exist_ok=True)
    produced = list(root.glob("*.gcov"))
    assert produced, f"gcov produced no .gcov files: {proc.stderr[:400]}"
    for item in produced:
        shutil.move(str(item), str(coverage_dir / item.name))

    # Some coverage tools report per-function data on stdout rather than inside
    # the .gcov files; persist it the way the coverage module does.
    functions = parse_tool_function_output(proc.stdout or "")
    if functions:
        write_function_sidecar(str(coverage_dir), functions)


@pytest.fixture
def analyzed(tmp_path):
    """Build both configurations and return (project, mapping, extraction)."""
    root = tmp_path / "proj"
    _write_project(root)

    enabled_dir = tmp_path / "cov_on"
    disabled_dir = tmp_path / "cov_off"

    _build_run_and_cover(root, True, enabled_dir)
    _build_run_and_cover(root, False, disabled_dir)

    mapping = map_feature_from_coverage(
        "MYFEATURE",
        load_coverage_dir(str(enabled_dir)),
        load_coverage_dir(str(disabled_dir)),
    )
    return root, mapping, extract_from_mapping(mapping)


class TestEndToEndMapping:
    def test_finds_the_interleaved_feature_code(self, analyzed):
        """The paper's central claim: code a build flag leaves behind."""
        _root, _mapping, extraction = analyzed

        main_lines = _lines_for(extraction, "main.c")
        source = MAIN_C.splitlines()

        # feature_helper's body executes only when the feature is on, and is not
        # inside any #ifdef, so the build flag alone cannot remove it.
        helper_body = source.index("    shared_counter += 1;") + 1
        assert helper_body in main_lines

    def test_does_not_remove_never_executed_code(self, analyzed):
        _root, mapping, extraction = analyzed

        main_lines = _lines_for(extraction, "main.c")
        source = MAIN_C.splitlines()
        never_body = source.index("    return value + 999;") + 1

        assert never_body not in main_lines
        # It is reported, so the completeness cost is visible.
        assert mapping.excluded_never_executed > 0

    def test_does_not_remove_shared_code(self, analyzed):
        _root, _mapping, extraction = analyzed

        main_lines = _lines_for(extraction, "main.c")
        source = MAIN_C.splitlines()
        core_body = source.index("    return value + 1;") + 1

        # core_work runs in both configurations.
        assert core_body not in main_lines

    def test_treats_the_feature_only_file_as_dedicated(self, analyzed):
        _root, _mapping, extraction = analyzed

        assert any(
            path.endswith("feature.c")
            for path in extraction.feature_only_source_paths
        )

    def test_reports_a_nonzero_mapping(self, analyzed):
        _root, _mapping, extraction = analyzed

        assert extraction.total_removable_lines > 0


class TestEndToEndRemoval:
    def test_removal_keeps_the_project_compiling(self, analyzed):
        root, mapping, extraction = analyzed

        result = remove_feature_code(
            extraction,
            str(root),
            "MYFEATURE",
            protected_lines=protected_lines(mapping),
            rebuild=True,
            build_command=["make", "WITH_MYFEATURE=no", f"CC={CC}"],
        )

        assert result.success is True, result.error_message
        assert result.rebuild_success is True
        assert result.restored is False

    def test_debloated_program_still_runs_and_produces_output(self, analyzed):
        root, mapping, extraction = analyzed

        remove_feature_code(
            extraction,
            str(root),
            "MYFEATURE",
            protected_lines=protected_lines(mapping),
            rebuild=True,
            build_command=["make", "WITH_MYFEATURE=no", f"CC={CC}"],
        )

        run = subprocess.run(["./app"], cwd=root, capture_output=True, text=True)

        assert run.returncode == 0, run.stderr
        assert "total=" in run.stdout

    def test_core_behaviour_is_unchanged_by_removal(self, analyzed):
        """The feature-disabled build must behave identically before and after."""
        root, mapping, extraction = analyzed

        subprocess.run(["make", "clean"], cwd=root, capture_output=True)
        subprocess.run(
            ["make", "WITH_MYFEATURE=no", f"CC={CC}", "COVERAGE="],
            cwd=root, capture_output=True, text=True,
        )
        before = subprocess.run(
            ["./app"], cwd=root, capture_output=True, text=True
        ).stdout

        remove_feature_code(
            extraction,
            str(root),
            "MYFEATURE",
            protected_lines=protected_lines(mapping),
            rebuild=False,
        )
        subprocess.run(["make", "clean"], cwd=root, capture_output=True)
        subprocess.run(
            ["make", "WITH_MYFEATURE=no", f"CC={CC}", "COVERAGE="],
            cwd=root, capture_output=True, text=True,
        )
        after = subprocess.run(
            ["./app"], cwd=root, capture_output=True, text=True
        ).stdout

        assert before == after

    def test_backup_can_restore_the_original_tree(self, analyzed):
        root, mapping, extraction = analyzed
        original = (root / "main.c").read_text()

        result = remove_feature_code(
            extraction,
            str(root),
            "MYFEATURE",
            protected_lines=protected_lines(mapping),
            rebuild=False,
        )
        assert (root / "main.c").read_text() != original

        from prat.removal import restore_from_backup

        assert restore_from_backup(result.backup_dir, str(root)) is True
        assert (root / "main.c").read_text() == original


class TestEndToEndFunctionCoverage:
    def test_function_coverage_is_available_from_real_gcov(self, analyzed):
        """Needed for the paper's per-variant function-coverage column."""
        root, _mapping, _extraction = analyzed
        coverage_dir = root.parent / "cov_on"

        parsed = load_coverage_dir(str(coverage_dir))
        covered = sum(len(g.covered_functions) for g in parsed.values())
        total = sum(len(g.functions) for g in parsed.values())

        if total == 0:
            pytest.skip("this gcov build does not emit per-function summaries")

        assert covered > 0
        assert covered <= total


class TestEndToEndBatch:
    def test_real_n_plus_one_builds_use_one_workload_plan(self, tmp_path):
        """Exercise Algorithm 1 through real compiler and coverage processes."""
        root = tmp_path / "batch-project"
        (root / "src").mkdir(parents=True)
        (root / "src" / "main.c").write_text(BATCH_MAIN_C)
        (root / "Makefile").write_text(BATCH_MAKEFILE)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=PRAT Test",
                "-c",
                "user.email=prat-test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=root,
            check=True,
        )

        output = tmp_path / "batch-results"
        result = run_batch_analysis(
            str(root),
            output_dir=str(output),
            adapter=BatchFixtureAdapter(str(root)),
        )

        assert result.success is True, result.error_message
        assert result.feature_names == ["ALPHA", "BETA"]
        assert result.builds_performed == 3
        assert result.mapping_build_states == [
            {"ALPHA": True, "BETA": True},
            {"ALPHA": False, "BETA": True},
            {"ALPHA": True, "BETA": False},
        ]
        assert result.feature_results["ALPHA"].removable_lines > 0
        assert result.feature_results["BETA"].removable_lines > 0

        plan_ids = {
            result.baseline_coverage.test_plan_id,
            result.feature_results["ALPHA"].coverage.test_plan_id,
            result.feature_results["BETA"].coverage.test_plan_id,
        }
        assert len(plan_ids) == 1
        assert None not in plan_ids
        assert result.source_commit
        assert (output / "batch_checkpoint.json").is_file()


def _lines_for(extraction, basename: str) -> set[int]:
    """Mapped line numbers for whichever recorded path ends with ``basename``."""
    for path, lines in extraction.file_line_numbers.items():
        if os.path.basename(path) == basename:
            return set(lines)
    return set()
