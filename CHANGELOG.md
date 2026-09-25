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
- **The single-feature path builds `B_all` and `B_f`, not default ± f.** `run_complete_workflow`
  (and therefore every Docker demo) discovers the feature set and builds every feature on versus
  every feature but `f`, as Algorithm 1 lines 4 and 8 specify. Previously it built the project's
  default configuration with `f` forced on and off while its documentation presented the result
  as `L_all \ L_f`. The checkpoint and demo manifest record `baseline_mode` (`"all-features"`) and
  the exact configuration of both builds in `mapping_build_states`; the old behaviour remains as
  `--default-baseline`, is labelled `"project-default"`, and strict validation rejects it.
- **One fixed test plan `T` runs against every build.** Algorithm 1 fixes `T` once (line 3) and
  runs it against `B_all` and each `B_f`. The single-feature path instead ran a polarity-specific
  workload per build, and the batch path ran the union of both polarities in every build, so for
  libaom, FFmpeg and Mosquitto-on-macOS the two coverage runs executed different commands and the
  mapping reflected the workload change as well as the feature. `ProjectAdapter.get_test_plan()`
  now supplies `T` independently of any feature's polarity; libaom and Mosquitto override it so
  part of `T` runs on every build. Tests of `f` that cannot pass against `B_f` are tolerated there
  and listed in the checkpoint (`tests_not_run_in_b_f`); against `B_all` every command must pass.
  The recorded digest is computed from the commands actually run, and a run whose `B_f` plan
  differs from its `B_all` plan fails.
- **Post-removal verification re-runs the same fixed `T`.** The workflow verified with the
  adapter's `enabled=False` workload and the batch path with the polarity union, and the
  reference oracle rejected any command that failed before removal, which a fixed `T` cannot
  satisfy. `capture_reference_outputs()` now records every command's outcome (`ReferenceOutcome`:
  exit code, normalized output, or why it could not run), and `verify_correctness()` requires each
  outcome to be reproduced. Tests of the removed feature are expected failures: failing identically
  is preserved behaviour, passing instead is divergence. A crash the reference also produced is
  reported as pre-existing. The single-feature path rebuilds the debloated program in `B_f`'s
  configuration, so the reference and the debloated build differ only by `D_f`.
- **Strict validation is satisfiable.** `validate_paper_results.py --strict` treated a missing
  `tolerance_pct` as an error while every published-value target sets it to `null`, so
  `make compatibility-check` could never pass. A tolerance band now applies only when one is
  configured, which is what the documentation already said.
- **Removal never writes outside the project tree.** gcov reports inline code the build executed
  in system headers (OpenSSL's `x509v3.h` under a TLS build); it reached `D_f`, and removal,
  joining an absolute path onto the project root, blanked a line in the Homebrew-installed
  header. Sources outside the project are now dropped from `L_all` and `L_f` before mapping
  (`restrict_to_project`, recorded as `out_of_tree_sources`) and refused by removal as a second
  line of defence.
- **Backup and restore work with a relative project path.** The backup flattened files to their
  basename whenever gcov recorded absolute source paths and the CLI was given a relative project
  path (the normal CMake case), so a failed removal "restored" copies to the project root while
  the real `lib/*.c` stayed modified. The project root is resolved once and the backup mirrors
  the tree.
- **A source compiled into two objects keeps both coverage readings.** Mosquitto builds `lib/*.c`
  into both libmosquitto and the broker, so gcov yields two `.gcov` files for one source; staging
  overwrote one with the other and then failed with "No coverage files generated". Their counts
  are now unioned per line.
- **Mosquitto on macOS: the TLS session actually runs.** The shipped `test/ssl` certificates in
  the 2.0.x tags have expired, so the TLS client failed and, under `set -e`, left the broker
  holding the port and the output pipes until the 300 s timeout. The adapter now generates its
  own CA and `localhost` certificate under `build/prat_ssl` and stops the broker on every exit
  path. CMake discovery passes `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` so CMake 4 can list the
  option cache.
- **A failed rebuild now fails the removal and restores the tree.** The paper relies on a broken
  build preventing an incorrect implementation from being produced; previously the failure was
  logged and the removal still reported success.
- **Removal preserves delimiter balance.** `D_f` contains only lines gcov attributes executable
  code to, so `if (x) {` can be mapped while its `}` cannot, and gcov puts a function's entry
  block on the *signature* line with the opening brace on the next. Blanking those in isolation
  produced files that do not compile. `plan_removal()` now joins runs separated only by
  non-executable structural lines, absorbs the delimiters needed to close a run, and declines any
  run it cannot balance.
- **Exact removal reasons about unexecuted code instead of declining it.** With the mapping
  corrected, roughly half of Mosquitto's `D_TLS` was declined: `if (mosq->ssl) {` was mapped
  while the body it guards ran in neither build, so no run could close. `plan_removal_detailed()`
  now distinguishes feature-only code `B_all` compiled but `T` never executed (absorbed: it is
  not in `B_f`), shared code `B_f` compiles but never executed (its guard is **kept** and
  reported in `RemovalResult.guards_shared_code`, since the paper forbids removing unexecuted
  lines), a delimiter-only run shared code needs (`retained_structural`), a mapped line `B_f`
  itself compiles (kept as a guard, not grouped with the feature code around it), and
  `if(f){A}else{B}` where `B` is live (collapses to `B`). A run whose delimiters are net closing
  is no longer bridged forward over a gap. `require_complete` accepts the two kept categories as
  disclosed residue and still fails on any genuine decline. A run merged during a walk and then
  declined is now re-planned rather than dropped from every category.
- **Mosquitto's fixed `T` grew from two sessions to seven**: plain, TLS publish/subscribe, mutual
  TLS with `require_certificate`, a `--capath`/`--ciphers`/`--tls-version`/`--tls-alpn` session,
  and three expected-failure probes (plain client on the TLS port, wrong CA, missing `cafile`).
  Both listener configurations carry a string-valued option so the generic config parser runs in
  both builds. On macOS this takes `|D_TLS|` from 398 to 600 lines and exact removal from
  failing to 501 removed, 99 kept for a disclosed reason, 0 declined; the debloated build
  rebuilds and reproduces every pre-removal outcome.
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

- **Single-feature runs emit the feature graph.** `build_feature_graph_from_single()` existed but
  nothing called it, so every single-feature run (and therefore every Docker demo) produced a
  report but no `feature_graph.html`; only `--batch` did. `run_complete_workflow` now writes the
  one-root graph next to `report.html` and records it as `ExtractionResult.feature_graph_path`.
- **The feature graph is fully offline.** `generate_feature_graph_html` loaded D3 from
  `cdn.jsdelivr.net`, contradicting the report's self-contained design goal. D3 v7.9.0 is now
  vendored (`prat/web/d3.v7.min.js`, ISC licence in `prat/web/D3-LICENSE`, SHA-256 verified by
  `prat.web.load_d3_bundle()`) and inlined into the generated page.
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
- `ProjectAdapter.get_test_plan(features)` — the fixed test plan `T` for a feature set. The
  default derives it from the all-features workload; libaom and Mosquitto override it.
- `prat.verification.ReferenceOutcome` — one command's pre-removal outcome (exit code,
  normalized output, or why it could not run), the unit the post-removal oracle compares.
  `VerificationResult.expected_failures` and `preexisting_crashes` report what was preserved.
- Checkpoint and manifest fields that make a run auditable: `baseline_mode`,
  `mapping_build_states`, `test_plan_id`, `test_plan_commands`, `test_plan_identical`,
  `tests_not_run_in_b_f` (per-feature `tests_not_run` in batch), and per-build
  `test_failures_tolerated` / `execution_errors` on coverage results.
- `ARTIFACT.md` — the reviewer's guide: first command, runtimes, disk, what success looks like.
- `--skip-feature NAME` (CLI and `demo_workflow.py`): leave a discovered build option out of
  `F` because the environment cannot compile it (a library that is not installed, a Linux-only
  option on macOS). Recorded as `features_excluded`; the analyzed feature itself cannot be
  skipped. The Mosquitto Docker images install the libraries the non-default options need
  (c-ares, jemalloc, systemd, libwrap) and CUnit for `make utest`, so no option needs skipping
  there.
- `results/README.md` is now tracked (it was linked from the README and CHANGELOG but had never
  been committed, because `results/` was ignored wholesale).
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
- `docs/sample-results/` — the committed "reviewer snapshot" was produced by the superseded
  mapping rule and scored against the invented per-feature values; it showed dead target slugs and
  `success: false` while labelled as evidence. No results are committed; see `results/README.md`.

### Notes

- `results/` is not committed (`results/README.md` explains why and how to regenerate). Rust
  coverage uses `cargo-llvm-cov` rather than the paper's `kcov`; the substitution and its reason
  are recorded in `REPRODUCIBILITY.md` §3 and `docs/PAPER_ALIGNMENT.md`.
- Eight compatibility demos cover all seven paper codebases.
- `ARTIFACT.md` gives reviewers the fastest trust path, the evidence path, runtime and disk
  expectations, and what success looks like.
- The `B_all` builds inside the pinned Docker images have not been re-run since the baseline
  correction. A demo whose all-features build does not compile fails loudly rather than
  substituting a different baseline.

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
