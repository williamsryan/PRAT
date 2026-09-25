#!/usr/bin/env python3
"""Replay the removal planner offline against a retained coverage pair.

Given the results directory of a completed run (which keeps the gcov output
for B_all and B_f), recompute D_f and run ``plan_removal_detailed`` for each
file WITHOUT modifying any source. Use it to answer "why was this mapped line
kept?" without re-running the builds.

Usage:
    python scripts/replay_removal_plan.py RESULTS_DIR PROJECT_DIR FEATURE [FILE_SUBSTR]

    RESULTS_DIR  a run's output dir containing coverage_files_WITH_<F>_yes/ and
                 coverage_files_WITH_<F>_no/
    PROJECT_DIR  the analysed project's source tree (same state as the run)
    FEATURE      the feature name used in the run (e.g. TLS)
    FILE_SUBSTR  optional; print per-range detail for files matching it

Each kept range is reported in the category the planner assigned it:
    SKIPPED  declined as unsafe (genuine incompleteness; fails require_complete)
    STRUCT   delimiter-only line that shared code still needs
    GUARD    condition of a block whose body was never executed in either build
"""

from __future__ import annotations

import sys
from pathlib import Path

from prat.gcov import load_coverage_dir
from prat.mapping import guard_context, map_feature_from_coverage, restrict_to_project
from prat.removal import _find_source_file, plan_removal_detailed


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    results = Path(argv[1]).resolve()
    project = Path(argv[2]).resolve()
    feature = argv[3]
    only = argv[4] if len(argv) > 4 else None

    enabled_dir = results / f"coverage_files_WITH_{feature}_yes"
    disabled_dir = results / f"coverage_files_WITH_{feature}_no"
    for d in (enabled_dir, disabled_dir):
        if not d.is_dir():
            print(f"error: missing coverage dir {d}")
            return 2

    enabled, _ = restrict_to_project(load_coverage_dir(str(enabled_dir)), str(project))
    disabled, _ = restrict_to_project(load_coverage_dir(str(disabled_dir)), str(project))
    mapping = map_feature_from_coverage(feature, enabled, disabled)
    ctx = guard_context(mapping)

    tot = dict(cand=0, approved=0, skipped=0, structural=0, guards=0)
    for source_path, fm in sorted(mapping.files.items()):
        if not fm.lines or (only and only not in source_path):
            continue
        src = _find_source_file(project, source_path)
        if src is None:
            print(f"!! not found in project: {source_path}")
            continue
        lines = src.read_text(errors="replace").splitlines()
        g = ctx.get(source_path)
        plan = plan_removal_detailed(
            lines,
            set(fm.lines),
            protected=set(fm.shared_lines),
            absorbable=set(g.absorbable) if g else None,
            unexecuted_feature_only=set(g.unexecuted_feature_only) if g else None,
            unexecuted_shared=set(g.unexecuted_shared) if g else None,
            executable_disabled=set(g.executable_disabled) if g else None,
        )
        cand = len(fm.lines)
        approved = len(plan.approved & set(fm.lines))
        tot["cand"] += cand
        tot["approved"] += approved
        tot["skipped"] += plan.skipped_lines
        tot["structural"] += plan.retained_structural_lines
        tot["guards"] += plan.guards_shared_code_lines
        print(
            f"{Path(source_path).name:28s} cand={cand:4d} approved={approved:4d} "
            f"skipped={plan.skipped_lines:3d} struct={plan.retained_structural_lines:3d} "
            f"guards={plan.guards_shared_code_lines:3d}"
        )
        if only:
            for lo, hi in plan.skipped:
                print(f"   SKIPPED {lo}-{hi}")
                for n in range(lo, hi + 1):
                    print(f"      {n:5d}: {lines[n - 1]}")
            for lo, hi in plan.retained_structural:
                print(f"   STRUCT  {lo}-{hi}: {lines[lo - 1].strip()!r}")
            for lo, hi in plan.guards_shared_code:
                print(f"   GUARD   {lo}-{hi}: {lines[lo - 1].strip()!r}")

    print(
        f"TOTAL candidates={tot['cand']} approved={tot['approved']} "
        f"skipped={tot['skipped']} struct={tot['structural']} guards={tot['guards']}"
    )
    return 1 if tot["skipped"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
