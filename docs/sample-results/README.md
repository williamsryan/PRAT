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
| aom-encoder | PASS (dynamic coverage) | 8691 | 54060 | 28000 | 5000–50000 |
| ffmpeg-x264 | runs via substitute `decoder=dca` (scope) | 54 | 3728 | 3241* | 1000–5000 |
| opendds-security | FAIL (runs; static over-counts generated code) | 49677 | 72262 | 2800 | 500–5000 |
| quiche-ffdhe | runs via substitute `qlog` (drift) | 420 | 420 | 450* | 100–1500 |

6 of 7 produce in-range results: 3 are the paper's own targets measured directly (mosquitto
TLS/BRIDGE; libaom via dynamic coverage), 1 via the paper-aligned feature-file metric
(azure-uamqp-c), and 2 via documented **substitute** features — ffmpeg→`decoder=dca` (x264's
code is in the external libx264 library PRAT doesn't compile) and quiche→`qlog` (`ffdhe` is not a
Cargo feature in 0.20.1). Substitutes are flagged inline as NOT reproductions of the paper value.
OpenDDS builds and runs end-to-end but its static differential is dominated by generated IDL
type-support churn — see `REPRODUCIBILITY.md`.

To regenerate: `make paper-check` (or `prat reproduce --all`), then
`python3 scripts/validate_paper_results.py results/docker/ --json results/validation_report.json`.
