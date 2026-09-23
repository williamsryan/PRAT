# Changelog

All notable changes to PRAT are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — unreleased

Corrects the feature-to-code mapping to the algorithm the paper specifies, and implements the
paper claims that had no corresponding code. The mapping change alters measured results, so
this is a major version and the committed results under `results/` must be regenerated.

### Fixed

- **Feature-to-code mapping now computes `D_f = L_all \ L_f`.** The mapping previously scanned a
  textual `diff -u` of two gcov files for the `#####` marker. In gcov, `#####` means *executable
  but never executed* — not "executed only when the feature is on" — so the old rule both missed
  the interleaved feature code the paper is about (which carries an execution *count*, not a
  `#####` marker, and so was never selected) and included lines the paper explicitly forbids
  removing, namely those never executed in either build and those still live with the feature
  off. On the paper's canonical case the old rule returned zero lines. `prat.gcov` now parses
  execution counts into line sets and `prat.mapping` computes the set difference.
- **Batch analysis performs Algorithm 1's `n+1` builds** against a single all-features baseline,
  rather than two builds per feature against project defaults. `BatchResult.builds_performed`
  reports the count; an all-features baseline failure now fails the Algorithm 1 run.
- **A failed rebuild now fails the removal and restores the tree.** The paper relies on a broken
  build preventing an incorrect implementation from being produced; previously the failure was
  logged and the removal still reported success.
- **Removal preserves delimiter balance.** `D_f` contains only lines gcov attributes executable
  code to, so `if (x) {` can be mapped while its `}` cannot, and gcov puts a function's entry
  block on the *signature* line with the opening brace on the next. Blanking those in isolation
  produced files that do not compile. `plan_removal()` now joins runs separated only by
  non-executable structural lines, absorbs the delimiters needed to close a run, and declines any
  run it cannot balance.
- **KLEE runs for 60 minutes, not 60 seconds.** `KleeConfig.max_time_minutes` matches the paper's
  Table 3 and converts to the seconds KLEE's flag expects.
- **Symbolically generated tests are actually used.** They were generated and discarded; they are
  now replayed against each instrumented build, so `T = U u S` holds in the runs that produce
  `D_f`.
- **`compile_to_bytecode()` links per-file modules with `llvm-link`.** A single
  `clang -emit-llvm -c a.c b.c -o out.bc` is an error, so bytecode compilation previously failed
  for any project with more than one source file.
- **Feature discovery matches the paper's criteria.** The CMake analyzer configures into a scratch
  build directory before reading `cmake -LA` (`-LA -N` only prints an existing cache and reported
  nothing on a clean tree) and also parses `set(... CACHE BOOL ...)` and `*_config_var()` macros;
  the autoconf analyzer applies the paper's "feature"/"optional" description filter and strips
  value placeholders; the Cargo analyzer excludes features that are transitive members of the
  `default` array; the Make analyzer is reachable, so Mosquitto's `config.mk`-only features
  (BRIDGE, PERSISTENCE, WEBSOCKETS, SYS_TREE, MEMORY_TRACKING) are discoverable. Discovery runs
  every applicable analyzer and merges the results instead of taking the first match.
- **Spurious and developer-specific options are filtered**, as the paper describes, including the
  build system's own variables.
- **Verification distinguishes crashes from failures** (reporting the signal), detects divergence
  from pre-removal behaviour when a reference was captured, and reports a run with no available
  tests as `INCONCLUSIVE` rather than a pass.
- **Feature graphs are the paper's three-tier DAG.** The LOC tier (leaves) existed only in the
  Graphviz export and only for files with five or fewer removable lines; contiguous-line merging
  was absent entirely. Both are implemented, and `_validate_graph()` checks unique vertices, tier
  ordering and acyclicity on every graph built.

### Added

- `prat.gcov` — gcov parsing, contiguous-run merging, and function-coverage extraction
  (`gcov -f`, with a sidecar for tools that report functions on stdout).
- `prat.mapping` — Algorithm 1's set difference, plus coverage and function-coverage statistics.
- `prat.variants` — the paper's cumulative variant chain, where variant *i* keeps variant *i-1*'s
  removals and adds one more. `prat <project> --variants 8`.
- `prat.fuzzing` — Boofuzz MQTT harness reporting per-variant line and function coverage and
  attributing crashes only when variant 0 did not also exhibit them. Optional dependency:
  `pip install 'prat[fuzz]'`. `prat <project> --variants 8 --fuzz`.
- Side-by-side code comparison reports (`prat.diff`): a coverage comparison for auditing the
  mapping, and an original-vs-debloated source comparison for auditing the removal.
- Multi-feature builds (`compile_with_adapter(feature_states=...)`,
  `ProjectAdapter.get_build_commands_for_set()`), needed for the all-features baseline.
- `BatchResult.union_removable_lines` — `|union of D_f|`, the quantity comparable to Table 4's
  PRAT column, since a line attributable to two features must be counted once.
- Removal and verification are part of `run_complete_workflow`; verification runs by default
  after `--remove` (`--no-verify` opts out).
- End-to-end integration test running the whole pipeline against a real compiler and real gcov.
- `make list-features-all`, `make variants-mosquitto`, `make fuzz-mosquitto`.
- An eighth Docker target, `rav1e-serialize`, covers the seventh paper codebase.

### Changed

- **`paper_expected_results.json` rewritten with traceable provenance.** Earlier revisions
  attributed seven per-feature values to "Table 4" (1247, 623, 3241, 890, 2800, 450, 28000); none
  appears anywhere in `paper/`, and Table 4 contains whole-program totals, not per-feature counts.
  Expected values now come from `paper/results/code_removal.csv` (the paper's per-feature data:
  TLS 790, Bridge 640, use_wsio 26, content-filtered-topic 73) and Table 4. Targets analyzing a
  feature the paper reports no value for carry `paper_lines_removed: null`.
- **The validator reports `OBSERVED` for targets with no published value** instead of scoring them
  against an invented range. Reporting deviations against fabricated targets is what made correct
  results look like failed reproductions.
- **`demo5` retargeted from `SECURITY` to `content-filtered-topic`**, one of the paper's five
  OpenDDS features and a real DDS-3.25 `configure` switch, so the codebase now has a published
  value to validate against.
- Demos renamed to the feature actually analyzed: `ffmpeg-x264` → `ffmpeg-dca`,
  `quiche-ffdhe` → `quiche-qlog`, `opendds-security` → `opendds-content-filtered-topic`. Demo
  metadata records the analyzed feature, so manifests no longer name a feature that was not run.
- `use_wsio` is used as azure-uamqp-c's WebSocket option — the paper's name for it.
  `USE_WEBSOCKETS` is not a CMake variable in that codebase.
- The `interleaved`/`combined` two-metric reporting is gone. Under the corrected mapping they are
  two partitions of one `D_f`, so there is a single figure; the dedicated-feature-file share is
  still reported separately.
- Coverage collection always requests `gcov -f`, and coverage-tool detection no longer looks for
  the Debian-9-era `llvm-cov-9` name first.

### Removed

- `prat.diff.diff_coverage_files` / `DiffResult` / `match_coverage_files` — the textual gcov diff
  the incorrect mapping was built on.
- `prat.extraction.count_removable_lines` — counted `#####` lines.
- `prat.reporting.generate_html_diffs` — pygmentize colouring of those diffs, superseded by the
  comparison reports.

### Notes

- `results/` and `docs/sample-results/` predate the mapping correction; see `results/README.md`.
- Rust coverage uses `cargo-llvm-cov` rather than the paper's `kcov`; the substitution and its
  reason are recorded in `REPRODUCIBILITY.md` §3 and `docs/PAPER_ALIGNMENT.md`.
- Eight compatibility demos cover all seven paper codebases.

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

[2.0.0]: https://github.com/williamsryan/PRAT/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/williamsryan/PRAT/releases/tag/v1.0.0
