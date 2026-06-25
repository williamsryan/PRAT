# Sample reproducibility snapshot

This directory is a **committed snapshot** of a real PRAT run so reviewers can
inspect outcomes without building anything. It was produced on Docker / Linux
aarch64 (Apple Silicon host). See [`../../REPRODUCIBILITY.md`](../../REPRODUCIBILITY.md)
for the full methodology and analysis.

## Contents

- `validation_report.json` — consolidated validation of all 7 targets against
  `paper_expected_results.json`.
- `<demo>/workflow_checkpoint.json` — per-demo machine-readable results
  (`total_removable_lines` = interleaved; `feature_only_removable_lines` and
  `total_feature_lines` = paper-aligned combined; `feature_only_source_paths`).
- `<demo>/manifest.json` — provenance: checked-out git commit (verified equal to
  the upstream tag), adapter, build system, compiler/tool versions, platform.
- `quiche-ffdhe/BLOCKED.json` — evidence that the `ffdhe` feature does not exist
  in quiche 0.20.1 (the demo cannot be constructed as specified).

## Summary (this snapshot)

| Target | Status | interleaved | combined | paper | range |
|--------|--------|-------------|----------|-------|-------|
| mosquitto-tls | PASS | 1415 | 1550 | 1247 | 500–1800 |
| mosquitto-bridge | PASS | 545 | 989 | 623 | 300–900 |
| uamqp-websockets | PASS (paper-aligned) | 0 | 1282 | 890 | 200–2000 |
| ffmpeg-x264 | FAIL (below) | 2 | 551 | 3241 | 1000–5000 |
| aom-encoder | FAIL (brackets paper) | 2837 | 85241 | 28000 | 5000–50000 |
| opendds-security | ERROR (not buildable as configured) | — | — | 2800 | 500–5000 |
| quiche-ffdhe | BLOCKED (feature absent) | — | — | 450 | 100–1500 |

To regenerate: `make paper-check` (or `prat reproduce --all`), then
`python3 scripts/validate_paper_results.py results/docker/ --json results/validation_report.json`.
