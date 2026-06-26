# Changelog

All notable changes to PRAT are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-06-26

First public release of the research artifact accompanying the ACM TOSEM 2021 paper
*"Guided Feature Identification and Removal for Resource-constrained Firmware"*
(doi:[10.1145/3487568](https://doi.org/10.1145/3487568)).

### Added
- End-to-end workflow API (`prat.workflow.run_complete_workflow`) and `prat` CLI
  (`analyze`, `--list`, `--batch`, `--dry-run`, `doctor`, `reproduce`, `--version`).
- Build-system adapters: Make (Mosquitto), Autotools (FFmpeg), CMake (azure-uamqp-c,
  libaom), Cargo/Rust (quiche), and the OpenDDS `configure`/MPC build.
- Two reported metrics: `interleaved` (feature code in shared files) and a paper-aligned
  `combined` measure that also counts dedicated feature-only files.
- Source-based Rust coverage via `cargo llvm-cov` with an lcov→gcov bridge.
- Seven reproducible Docker demos covering the paper's Table 4 targets, with a disk-safe
  `make paper-check` (per-demo build → run → image cleanup).
- `scripts/validate_paper_results.py` validating results against `paper_expected_results.json`,
  with provenance manifests recording pinned git commits and tool versions.
- Reproducibility report (`REPRODUCIBILITY.md`) and committed sample results
  (`docs/sample-results/`).

### Notes
- Reproduction is honest, not forced: where a paper feature is not directly measurable in the
  pinned version (FFmpeg x264's external library; quiche's nonexistent `ffdhe` Cargo feature),
  a documented in-tree substitute feature is analyzed and clearly labeled as *not* a
  reproduction of the paper value. No acceptance ranges were tuned to pass.

[1.0.0]: https://github.com/williamsryan/PRAT/releases/tag/v1.0.0
