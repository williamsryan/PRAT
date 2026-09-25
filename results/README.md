# Results directory

**No PRAT results are committed to this repository.** Everything under `results/`
is generated on the machine that runs the demos and is ignored by git (see
`.gitignore`). A reviewer who wants numbers must produce them; the repository
does not ship a snapshot to be taken on trust.

## Why nothing is committed

Earlier revisions committed a results snapshot (`docs/sample-results/`, a
`validation_report.json`, and a root `demo_report.txt`). Those files were produced
by a superseded mapping rule and were scored against per-feature "paper" values
that do not appear in the paper. They were removed rather than left in place with
a warning, because a snapshot that contradicts the current algorithm is worse than
no snapshot. The correction itself is described in `REPRODUCIBILITY.md` §1–2.

If a stale `demo_report.txt`, `validation_report.json`, or `docker/` tree is
present in your working copy, it is a local leftover from an earlier run; delete
it or regenerate.

## Generating results

```bash
# Disk-safe compatibility corpus: map → remove → verify each source-pinned target
make compatibility-check

# One demo at a time (remove the multi-GB image afterwards):
python3 src/demo-runner.py --build mosquitto-tls
python3 src/demo-runner.py --run mosquitto-tls --cleanup --output results/docker

# Score whatever has run
python3 scripts/validate_paper_results.py results/docker/ \
    --json results/validation_report.json
```

## What a result contains

Each `results/docker/<target>/` holds the demo's `workflow_checkpoint.json`
(mapping, removal and verification evidence), `manifest.json` (source commit,
tool versions, run identity), the `report.html` / `FDG.dot` / `report.json`
outputs, and the paper-style `comparison_reports/`.

`validate_paper_results.py` scores a target `COMPATIBLE` only when the evidence
chain is complete (pinned commit verified, dynamic execution on both builds, exact
removal, post-removal verification passed) **and** the paper publishes a value for
the analyzed feature. Targets with no published value are `OBSERVED`. The
deviation from the published value is reported; no numeric acceptance band is
applied unless one is configured in `paper_expected_results.json`, because the
paper does not record the source revisions it measured. See `REPRODUCIBILITY.md`
§5 for the full status table.
