# Paper Alignment — PRAT Implementation vs. Paper Claims

**Paper**: Williams et al., "Guided Feature Identification and Removal for Resource-constrained Firmware," ACM Transactions on Software Engineering and Methodology (TOSEM), 2021.
**DOI**: [10.1145/3487568](https://doi.org/10.1145/3487568)

This document maps the paper's claims to the code that implements them and the tests that pin them, so a reader can check each claim rather than take it on trust.

Every number quoted as a paper value in this repository is traceable to a specific table or data file under `paper/`. Where the paper reports no value for something this repo measures, that is stated explicitly rather than filled in with an estimate. See `paper_expected_results.json` for the provenance of each figure.

---

## C1: Feature-to-code mapping by differential coverage

**Paper, Algorithm 1**:

```
S     <- SymbolicTestGeneration(P)
T     <- U u S
B_all <- Compile(P)
L_all <- CoverageAnalysis(B_all, T)
for each f in F:
    P_f <- DisableFeature(P, f)
    B_f <- Compile(P_f)
    L_f <- CoverageAnalysis(B_f, T)
    D_f <- L_all \ L_f
```

**Paper, Correctness**: "removing only those LOCs that are executed when the relevant feature is active, but not when the same feature is disabled. The algorithm **does not remove** LOCs that are never executed regardless of whether the feature is active or not. … This design purposely strives for soundness over completeness."

| Paper concept | Code | Key function |
|---|---|---|
| Parse gcov execution counts into line sets | `src/prat/gcov.py` | `parse_gcov()`, `load_coverage_dir()` |
| `D_f = L_all \ L_f` | `src/prat/mapping.py` | `map_feature_from_coverage()` |
| Algorithm 1 over all features (n+1 builds) | `src/prat/batch.py` | `run_batch_analysis()` |
| Single-feature pipeline (`B_all` vs `B_f`, two builds) | `src/prat/workflow.py` | `run_complete_workflow()` |
| Compile with a given feature set | `src/prat/compilation.py` | `compile_with_adapter(feature_states=...)` |
| The fixed test plan `T` | `src/prat/adapters/base.py` | `ProjectAdapter.get_test_plan()` |
| Execute `T` for dynamic coverage | `src/prat/coverage.py` | `execute_for_coverage(execution_commands=..., allow_failures=...)` |
| Package D_f for reporting/removal | `src/prat/extraction.py` | `extract_from_mapping()` |

The mapping is a **set difference over executed lines**, not a textual diff of gcov files. This matters: gcov marks a line that is compiled but never run as `#####`, and marks a line the preprocessor removed as `-`. A line that is feature code in the paper's sense appears as a *count* in the feature-enabled build and as `-` or `#####` in the disabled build, so it produces no `#####` marker of its own. Selecting `#####` lines would therefore both miss the code the paper targets and remove code the paper explicitly excludes.

**Tests**: `src/tests/test_mapping.py` pins all three line classes — executed-only-when-enabled (removed), executed-when-disabled (kept, it is shared), and never-executed-in-either (kept, per the conservatism claim). `src/tests/test_gcov.py` pins the gcov parsing. `src/tests/test_batch.py::TestAlgorithmOneBuildCount` asserts the build count is n+1 and that each build leaves exactly one feature off. `src/tests/test_workflow.py::TestAlgorithmOneBaseline` asserts the single-feature path builds `B_all` and `B_f` over the discovered feature set and runs one `T` against both.

**Reproduce**:
```bash
prat App/mosquitto TLS          # one feature: B_all vs B_TLS
prat App/mosquitto --batch      # Algorithm 1 over every discovered feature
```

### n+1 builds, and what the baseline is

`run_batch_analysis` compiles `B_all` once, collects `L_all` once, and reuses it for every feature — n+1 builds for n features, as the paper specifies. `BatchResult.builds_performed` records the count so it can be checked.

`B_all` enables **every discovered feature**, and `B_i` enables all but `f_i`. If the all-features build does not compile, the Algorithm 1 run fails instead of silently changing the baseline. Build options whose leave-one-out build fails are discarded, as the paper describes, and listed in `BatchResult.discarded_options`.

The single-feature path (`prat <project> <feature>`, and every Docker demo) is the two-build slice of the same algorithm: it discovers `F`, builds `B_all` with every feature on and `B_f` with every feature but `f`, and records both configurations in `mapping_build_states` and `baseline_mode = "all-features"`. Earlier revisions built the project's *default* configuration with `f` forced on and off, which is not the paper's quantity; that mode still exists as `--default-baseline`, is labelled `baseline_mode = "project-default"`, and is rejected by the strict validator.

### One test plan, run against every build

Algorithm 1 fixes `T = U u S` once (line 3) and runs that same `T` against `B_all` and each `B_f` (lines 5 and 9). The adapter supplies `T` through `get_test_plan(features)`, which must not depend on which feature is being analysed. Both paths run it unchanged against every build and record a digest of the commands actually executed per build; a run whose `B_f` digest differs from its `B_all` digest fails, and the checkpoint records `test_plan_id` and `test_plan_identical`.

Because `T` is fixed, it contains the tests that exercise `f`, and those cannot pass against `B_f`. Against `B_all` every command of `T` must succeed. Against `B_f` a failing command is tolerated: it is listed in the checkpoint (`tests_not_run_in_b_f`, or per-feature `tests_not_run` in batch) and contributes no coverage, and `L_f` comes from the rest of `T`. At least one command must still run, or `L_f` would be empty and `D_f = L_all`. Adapters whose whole workload needs the feature therefore provide a plan with a feature-independent part; the Mosquitto adapter's plain-listener session alongside its TLS session is the pattern. The polarity-specific `get_execution_commands(feature, enabled=False)` is no longer used for mapping.

Earlier revisions ran a different workload per build (the single-feature path) or the union of both polarities in every build (the batch path); the mapping then reflected the workload change as well as the feature.

The explicit `--default-baseline` mode is available for exploratory analysis, but its output is not accepted by the strict Algorithm 1 validator.

### Sum vs. union

`BatchResult.total_removable_lines` is the sum of `|D_f|`. `BatchResult.union_removable_lines` is `|union of D_f|` — the right quantity to compare against Table 4's "No features (PRAT)" column, because a line attributable to two features must be counted once.

---

## C2: Feature identification from build configurations

**Paper definition**: "A feature is a set of lines of code which can be selectively activated or deactivated by operating on a single build configuration option."

| Paper claim | Code | Notes |
|---|---|---|
| cMake: `cmake -LA \| grep BOOL` | `discovery.py::_cmake_features_from_cache()` | Configures into a scratch build dir first, because `cmake -LA -N` only prints an existing cache and reports nothing on a clean tree |
| cMake (supplement) | `discovery.py::_cmake_features_from_sources()` | Also parses `option()`, `set(... CACHE BOOL ...)` and `*_config_var()` macros, for descriptions and for projects that declare options through a macro (libaom declares every `CONFIG_*` toggle via `set_aom_config_var`) |
| Autoconf: `configure --help`, retain descriptions containing "feature" or "optional" | `discovery.py::discover_features_autotools()` | Runs the script with its own interpreter (OpenDDS's `configure` is Perl, so forcing `bash` fails). Value placeholders are stripped, so no `decoder=NAME` names |
| Cargo: non-default features from `Cargo.toml` | `discovery.py::discover_features_cargo()` | Excludes features that are *members* of the `default` array, transitively, not just the `default` key. Reads workspace members |
| Make: `WITH_*` toggles | `discovery.py::discover_features_make()` | Mosquitto declares BRIDGE, PERSISTENCE, WEBSOCKETS, SYS_TREE and MEMORY_TRACKING only in `config.mk` |
| Discard spurious options; hide debug/developer options | `discovery.py::filter_features()` | Denylist of standard options plus naming heuristics; also drops the build system's own variables (`CMAKE_*`) |

`discover_features()` runs **every** analyzer whose build system is present and merges the results. Mosquitto ships both `CMakeLists.txt` and `config.mk` and exposes different features through each, so taking only the first matching build system loses features — including BRIDGE, which this repo ships a demo for.

Discovery reports the build option verbatim in `Feature.raw_name`; turning that into a flag is the adapter's job, since the same option is `WITH_TLS=yes` for Make and `-DWITH_TLS=ON` for CMake. Adapters that re-add a prefix implement `normalize_feature_name()`.

**Tests**: `src/tests/test_discovery.py`.

**Reproduce**:
```bash
prat App/mosquitto --list            # candidate features
prat App/mosquitto --list --verbose  # also reports how many options were filtered
```

---

## C3: Feature graphs

**Paper**: "A feature graph is a directed acyclic graph (DAG) F = {V, E}. The set of vertices V includes nodes representing features, source files, and sets of lines of code. … for each line of code of interest `l_i`, we establish an edge `(s, l_i)`. In practice, contiguous lines of code are merged in a single node. … the roots are features, intermediate nodes are source files, and leaves are lines within source files."

| Paper concept | Code | Key function |
|---|---|---|
| Three-tier DAG construction | `src/prat/feature_graph.py` | `build_feature_graph()`, `build_feature_graph_from_single()` |
| LOC leaves, one per contiguous run | `src/prat/feature_graph.py` | `_add_loc_nodes()` |
| Contiguous-line merging | `src/prat/gcov.py` | `merge_contiguous()`, `format_ranges()` |
| DAG invariant checking | `src/prat/feature_graph.py` | `_validate_graph()` |
| Interactive HTML | `src/prat/feature_graph.py` | `generate_feature_graph_html()` |
| Graphviz export | `src/prat/reporting.py` | `generate_dot_graph()` |
| Cross-feature file overlap | `src/prat/batch.py` | `CrossFeatureMap` |

All three tiers are emitted. Leaves are *sets* of lines: a feature spanning lines 12–14, 44 and 91–92 contributes three leaves, not six. `_validate_graph()` runs on every built graph and checks unique vertex ids, resolvable edge endpoints, no self-loops, the feature → file → loc tier order, and acyclicity.

A line range attributed to two features is one vertex with both features recorded, so `V` stays a set.

**Tests**: `src/tests/test_feature_graph.py`, including `TestGraphInvariants`.

**Reproduce**:
```bash
prat App/mosquitto --batch --output results/batch/
# → results/batch/feature_graph.html   (interactive, all three tiers, offline)
# → results/batch/FDG.dot              (Graphviz)

prat App/mosquitto TLS --output results/tls/
# → results/tls/feature_graph.html     (same graph, one root: TLS → files → line sets)
```

Both graphs are single self-contained HTML files. D3 v7.9.0 is vendored in `src/prat/web/`
(`d3.v7.min.js`, SHA-256 pinned and checked on load, licence in `D3-LICENSE`) and inlined at
generation time, so the page renders on an air-gapped machine.

---

## C4: Feature removal

**Paper**: "It then performs feature removal by removing from the source the lines in the union of `D_i`, and rebuilds the program binary." and "removing a feature without removing dependent features would result in breaking the build, which would still prevent an incorrect implementation from being generated."

| Paper concept | Code | Key function |
|---|---|---|
| Remove the mapped lines | `src/prat/removal.py` | `remove_feature_code()` |
| Delimiter-balance guard | `src/prat/removal.py` | `plan_removal()`, `compute_line_deltas()` |
| Rebuild as a gate | `src/prat/removal.py` | `remove_feature_code(rebuild=True)` |
| Backup / restore | `src/prat/removal.py` | `restore_from_backup()` |

Two things the paper's argument requires:

**The build is a gate.** A failed rebuild makes the removal fail (`RemovalResult.success is False`) and restores the tree from backup. The paper's safety net only holds if a broken build stops the process rather than being logged.

**Delimiter balance is preserved.** `D_f` contains only lines gcov attributes executable code to; a closing brace is never such a line. So `if (x) {` can enter `D_f` while its matching `}` cannot, and blanking the opener alone closes the enclosing function early. The guard joins runs separated only by non-executable structural lines (gcov puts a function's entry block on its *signature* line and the opening brace on the next), absorbs the delimiters needed to close a run, and declines any run it cannot balance. Declined runs are reported in `RemovalResult.skipped_unbalanced`.

Lines are blanked rather than deleted, so line numbering stays valid for later gcov runs and for the stored mapping.

**Tests**: `src/tests/test_removal.py` — including a pair that compiles the result and shows the guard is load-bearing (unguarded removal of the same lines fails to compile). `src/tests/test_integration.py` does this against a real compiler and real gcov end to end.

**Reproduce**:
```bash
prat App/mosquitto TLS --remove    # removes, rebuilds, then verifies
```

---

## C5: Post-removal correctness

**Paper**: "the system then re-runs the test suite, `T`, generated during feature-to-code-mapping and monitors the program's output for crashes and unexpected behavior."

| Paper concept | Code | Key function |
|---|---|---|
| Rebuild the debloated tree in `B_f`'s configuration | `src/prat/verification.py` | `verify_correctness(build_commands=...)` |
| Re-run the same fixed `T` | `src/prat/verification.py` | `verify_correctness(test_commands=...)`, `_run_test_suite()` |
| Replay S (KLEE tests) | `src/prat/verification.py` | `verify_correctness(symbolic_result=...)` |
| Crash detection | `src/prat/verification.py` | `_signal_name()` |
| Unexpected-behaviour oracle | `src/prat/verification.py` | `capture_reference_outputs()`, `ReferenceOutcome` |
| Side-by-side comparison reports | `src/prat/diff.py` | `generate_comparison_reports()` |

Verification runs by default after `--remove`; `--no-verify` opts out.

**The suite re-run is `T`**, the fixed plan the mapping ran, not a different workload. Before removal, `capture_reference_outputs()` runs every command of `T` against the pre-removal build in the removal configuration (`B_f` for one feature, all-features-disabled for batch union removal) and records each outcome: exit code and normalized output, or the reason the command could not run. After removal and rebuild in the same configuration, `verify_correctness()` runs `T` again and requires every outcome to be reproduced.

Because `T` contains the tests of the removed feature, some of those reference outcomes are failures. That is the expected result of removing `f`, and the debloated build is required to fail those tests **the same way**: same exit code, same normalized output. A test that failed before removal and fails identically after it is an *expected failure* (`VerificationResult.expected_failures`), counts as preserved behaviour, and is excluded from the pass rate. A test that now passes where it failed, fails where it passed, prints something different, or can no longer be started, *diverged*, and the verification fails. A test killed by a signal *crashed*, and the signal is named; a crash the reference build also produced with the same signal is reported as `preexisting_crashes` rather than as a crash introduced by removal.

A reference in which no command of `T` passes is refused before removal starts: there would be nothing for verification to preserve. A run that compiles but finds **no tests** is reported as `INCONCLUSIVE`, not as a pass: compiling is necessary but not sufficient evidence of correctness. Divergence is only reported when a reference was captured beforehand; otherwise the result says the check was not performed rather than implying it passed.

Earlier revisions verified with the adapter's `enabled=False` workload (a different suite from the one that produced `D_f`) and required every reference command to pass, which a fixed `T` cannot satisfy.

The paper's "code comparison reports which display, side-by-side, the original code and the code post-debloating, highlighting feature-relevant code" are produced by `prat.diff` in two forms: a coverage comparison (per line, its state in both builds, with `D_f` marked) for auditing the *mapping*, and a source comparison (original against post-removal) for auditing the *removal*.

**Tests**: `src/tests/test_verification.py` (including `TestReferenceOracle`), `src/tests/test_workflow.py::TestAlgorithmOneBaseline::test_verification_reruns_the_fixed_t_in_b_f_configuration`, `src/tests/test_diff.py`.

---

## C6: Symbolic test generation (KLEE)

**Paper Table 3** parameters, and: "We run KLEE against our target protocols for **60 minutes** and, on average, generate 4,369 tests."

| Paper concept | Code | Key function |
|---|---|---|
| Table 3 parameters | `src/prat/symbolic.py` | `KleeConfig` |
| Compile to one LLVM module | `src/prat/symbolic.py` | `compile_to_bytecode()` |
| Run KLEE | `src/prat/symbolic.py` | `run_klee()` |
| Replay via `klee-replay` | `src/prat/symbolic.py` | `replay_tests()` |
| Include S in T | `src/prat/coverage.py` | `execute_for_coverage(symbolic_tests=...)` |

`max_time` is stored as **minutes** (`KleeConfig.max_time_minutes = 60`) and converted to the seconds KLEE's flag expects. Configuring 60 *seconds* would generate a small fraction of the paper's test count, and since the mapping is bounded by the coverage `T` achieves, it would understate every feature.

`compile_to_bytecode()` compiles each source separately and links with `llvm-link`: `clang -emit-llvm -c a.c b.c -o out.bc` is an error, so a single invocation cannot produce the whole-program module KLEE needs.

Generated tests are passed into coverage collection and replayed against each instrumented build, so `T = U u S` holds in the runs that produce `D_f`.

**Status**: when `--symbolic` is requested, unavailable or failed KLEE execution fails the
workflow. `--paper-algorithm` makes symbolic generation mandatory together with the all-features
baseline, union removal, and post-removal verification. Ordinary analysis may explicitly use
`T = U` by omitting that mode. The KLEE path consumes C/C++ LLVM bitcode; Cargo/Rust symbolic
requests fail closed rather than claiming this paper step ran.

**Tests**: `src/tests/test_symbolic.py`.

---

## C7: Cumulative variants and fuzzing

**Paper**: "we generated 8 variants of Mosquitto. … variant *i* is obtained from variant *i-1* by selecting and deactivating a feature that was active in variant *i*", fuzzed with "a custom MQTT fuzzing engine based on the popular Boofuzz fuzzer", reporting per-variant line coverage, function coverage and session time.

| Paper concept | Code | Key function |
|---|---|---|
| Cumulative variant chain | `src/prat/variants.py` | `build_variant_chain()` |
| Boofuzz MQTT harness | `src/prat/fuzzing.py` | `define_mqtt_requests()`, `fuzz_variant()` |
| Per-variant line + function coverage | `src/prat/fuzzing.py` | `FuzzResult` |
| Crash attribution against variant 0 | `src/prat/fuzzing.py` | `compare_to_baseline()` |
| Function-level coverage | `src/prat/gcov.py` | `GcovFile.function_coverage()` |

The chain is distinct from the mapping in C1. There, every feature is isolated against the same all-features baseline (a star); here each variant keeps the previous variant's removals and adds one more (a chain), which is what exercises feature *interaction*. Each variant's `D_f` is computed against the *previous variant*, not the original baseline, because after TLS is removed the code attributable to TLS_PSK is different.

`FuzzResult` carries total/covered lines, total/covered functions and duration, so `FuzzCampaign.table()` renders the paper's table shape directly. Function coverage requires `gcov -f`, which the coverage module now always requests; tools that report functions on stdout rather than in the `.gcov` file are handled via a sidecar (`parse_tool_function_output`).

A crash counts as introduced by removal only if variant 0 did not also exhibit it — the paper uses variant 0 "as a baseline for #crashes present in the source prior to feature removal".

Boofuzz is an optional dependency. The registered MQTT packets (CONNECT, PUBLISH, SUBSCRIBE, PINGREQ, DISCONNECT) are asserted to render as valid MQTT 3.1.1 with self-consistent remaining-length framing, so the broker parses them rather than rejecting them on length.

**Tests**: `src/tests/test_variants.py`, `src/tests/test_fuzzing.py`.

**Reproduce**:
```bash
pip install 'prat[fuzz]'
prat App/mosquitto --variants 8 --fuzz --fuzz-seconds 600
```

---

## Coverage tooling

The paper states the prototype "leverages `gcov` (for C/C++) and `kcov` (for Rust)".

C/C++ uses `gcov` as described. **Rust uses `cargo-llvm-cov`, not `kcov`** — a substitution, recorded here and in `REPRODUCIBILITY.md`. The reason is that `cargo-llvm-cov` is the maintained, source-based coverage path for current stable Rust and works on the toolchains the demos pin; `kcov`, a DWARF/breakpoint-based tool, is unmaintained for recent Rust and unavailable on some of the platforms the demos target. The lcov output is converted to PRAT's gcov representation, so the mapping algorithm is identical across languages; only the instrumentation differs.

---

## Evaluation targets

The paper evaluates seven codebases (Table 5, Table 4): Mosquitto, azure-uamqp-c, OpenDDS, Quiche, FFmpeg, rav1e, libaom.

| # | Demo | Project | Build | Feature analyzed | Paper value for this feature |
|---|---|---|---|---|---|
| 1 | `mosquitto-tls` | Mosquitto v2.0.15 | make | `TLS` | **790** LOC (`paper/results/code_removal.csv`) |
| 2 | `mosquitto-bridge` | Mosquitto v2.0.15 | make | `Bridge` | **640** LOC |
| 3 | `ffmpeg-dca` | FFmpeg n5.1.4 | autotools | `decoder=dca` | none — the paper reports no per-feature LOC for FFmpeg |
| 4 | `uamqp-websockets` | azure-uamqp-c v1.2.0 | cmake | `use_wsio` | **26** LOC |
| 5 | `opendds-content-filtered-topic` | OpenDDS DDS-3.25 | MPC | `content-filtered-topic` | **73** LOC |
| 6 | `quiche-qlog` | quiche 0.20.1 | cargo | `qlog` | none — no per-feature LOC for Quiche |
| 7 | `rav1e-serialize` | rav1e v0.7.1 | cargo | `serialize` | none — no per-feature LOC for rav1e |
| 8 | `aom-encoder` | libaom v3.7.1 | cmake | `CONFIG_AV1_ENCODER` | none — no per-feature LOC for libaom |

Three points about this table, all of which were wrong in earlier revisions of this repo:

**The paper's per-feature data is `paper/results/code_removal.csv`** — 25 features across Mosquitto, azure-uamqp-c and OpenDDS, the data behind the paper's per-feature code-reduction figure. **Table 4 contains whole-program totals** with all features removed, not per-feature counts. Earlier revisions attributed invented per-feature numbers (1247, 623, 3241, 890, 2800, 450, 28000) to "Table 4"; none of those values appears anywhere in the paper, and reporting deviations against them made correct results look like failed reproductions.

**Four demos analyze features the paper does not report a line count for.** Those are measured and reported, and scored as `OBSERVED` rather than pass/fail, because there is no published value to compare against. `decoder=dca` is used for FFmpeg because x264's removable code lives in the external `libx264` library that FFmpeg only links; `qlog` is used for quiche because `ffdhe` is a BoringSSL TLS setting and not a Cargo feature in any release.

**All seven paper codebases have a source-pinned compatibility demo.** The rav1e demo analyzes its
real non-default `serialize` Cargo feature and is observational because the paper publishes no
per-feature rav1e line count.

Feature counts (Mosquitto 19, azure-uamqp-c 16, OpenDDS 9, Quiche 4, FFmpeg 33, rav1e 14, libaom 20; 115 total) are recorded in `paper_expected_results.json` under `feature_counts` for comparison against `prat --list`.

### Comparing with paper-reported values

```bash
make compatibility-check
python3 scripts/validate_paper_results.py results/docker/ --json results/validation_report.json
```

The validator requires current run provenance, successful dynamic execution, exact source commit,
source removal, and post-removal verification in strict mode. It scores a target only when the
paper publishes a value for the feature. Because the paper does not record source commits, these
scores are compatibility comparisons rather than exact reproduction claims.

---

## Docker demos

Self-contained demos (`docker/demo1`–`demo8`) that verify an exact source commit:

```bash
make compatibility-check
make docker-build && make docker-run
prat reproduce mosquitto-tls
prat reproduce --all
```

Each demo runs one feature through mapping, exact removal, rebuild, and test replay.
`prat App/<project> --paper-algorithm` is the complete Algorithm 1 path over all features.
