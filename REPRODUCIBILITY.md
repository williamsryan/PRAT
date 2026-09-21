# PRAT — Reproducibility

**Tool:** PRAT (Program feature Analysis Toolkit) — differential dynamic coverage analysis for
feature identification and removal.
**Paper:** Williams et al., *Guided Feature Identification and Removal for Resource-constrained
Firmware*, ACM TOSEM 2021 ([doi:10.1145/3487568](https://doi.org/10.1145/3487568)).

> **Status: results require regeneration.** The mapping algorithm was corrected (see §1), so the
> result files committed under `results/` were produced by the superseded rule and do not reflect
> what PRAT computes. `results/README.md` records this. This document describes the methodology,
> the provenance of every paper number, and how to regenerate and validate — it does not quote
> measurements from a run that predates the correction.

---

## 1. What was corrected, and why earlier numbers were wrong

Algorithm 1 defines feature-to-code mapping as a set difference over **executed** lines:

```
L_all = CoverageAnalysis(B_all, T)     # executed, all features enabled
L_f   = CoverageAnalysis(B_f,   T)     # executed, feature f disabled
D_f   = L_all \ L_f
```

constrained by the paper's Correctness subsection:

> "removing only those LOCs that are executed when the relevant feature is active, but not when
> the same feature is disabled. The algorithm **does not remove** LOCs that are never executed
> regardless of whether the feature is active or not. … This design purposely strives for
> soundness over completeness."

The implementation instead ran `diff -u` over two gcov **text files** and selected lines
containing the `#####` marker. In gcov, `#####` means *executable but never executed*. That rule
diverges from the algorithm in both directions:

- **It missed the code the paper is about.** A line that is feature code shows an execution
  *count* in the feature-enabled build and `-` (no code generated) or `#####` in the disabled
  build. It therefore carries no `#####` marker of its own and was never selected. On the
  canonical case — interleaved feature code that a build flag does *not* remove, which is the
  paper's central finding — the old rule returned **zero lines**.
- **It included code the paper excludes.** Every `#####` line inside a diff hunk was selected
  regardless of which side of the diff it came from, including lines never executed in either
  build (explicitly forbidden) and lines still live with the feature switched off.

This is the root cause of the reproduction problems: targets reporting 0, counts wandering far
from the paper's, and the pressure to substitute features or widen tolerances. It was not a
tolerance problem or a codebase-drift problem.

**Now:** gcov execution counts are parsed into line sets (`src/prat/gcov.py`) and `D_f` is a real
set difference (`src/prat/mapping.py`). The three line classes are pinned by
`src/tests/test_mapping.py`, and `src/tests/test_integration.py` runs the whole pipeline against a
real compiler and real gcov on a project shaped like the paper's case.

Four further corrections affect measured numbers:

| Area | Was | Now |
|---|---|---|
| Batch analysis | 2 builds per feature, baseline = project defaults | Algorithm 1's **n+1 builds**, baseline = all features enabled (with a reported fallback if that does not compile) |
| Removal | Rebuild failure logged, removal reported successful | Rebuild failure **fails the removal and restores** the tree; a delimiter-balance guard prevents removals that would not compile |
| KLEE | `max_time = 60` **seconds**; generated tests discarded | `max_time_minutes = 60` per Table 3; tests are replayed into coverage, so `T = U u S` |
| Function coverage | Not collected | `gcov -f` always requested; available for the paper's per-variant table |

---

## 2. Provenance of every paper number

`paper_expected_results.json` is the single source of expected values, and each is traceable:

| What | Where in the paper |
|---|---|
| **Per-feature LOC removed** (25 features) | `paper/results/code_removal.csv` — the data behind the per-feature code-reduction figure. Includes both the PRAT figure and the manual-deactivation figure |
| **Whole-program totals** (7 codebases) | Table 4 (`paper/tab_codereduction.tex`) — LOC and binary size with *all* optional features removed |
| **Feature counts** (115 total) | Feature Analysis section |
| **Coverage / runtime figures** | 80.2% KLEE coverage, 39.6% symbolized, 4,369 tests, 60-minute budget, 12.8-minute pipeline |

### A correction worth stating plainly

Earlier revisions of this repository attributed seven per-feature values to "Table 4":

| Target | Claimed as "paper" | Actually in the paper |
|---|---|---|
| mosquitto TLS | 1247 | **790** (`code_removal.csv`) |
| mosquitto Bridge | 623 | **640** |
| uamqp websockets | 890 | **26** (`use_wsio`) |
| ffmpeg x264 | 3241 | not reported |
| opendds SECURITY | 2800 | not reported (`SECURITY` is not a feature the paper analyzes) |
| quiche ffdhe | 450 | not reported |
| aom encoder | 28000 | not reported |

None of those seven values appears anywhere in `paper/`. Table 4 contains whole-program totals,
not per-feature counts. Reporting deviations against invented targets is what made correct
behaviour look like failed reproduction, and it is the most likely origin of claims that the
tool's results falsify the paper.

Targets for which the paper publishes no per-feature value are now scored `OBSERVED`: the
measurement is reported, and it is explicitly *not* counted as a reproduction, because there is
nothing published to compare it to.

---

## 3. Platform and environment

- **Host used during development:** macOS (Apple Silicon, arm64) with Docker Desktop.
- **Containers:** Linux aarch64. Each demo clones its target at a pinned tag, builds it twice
  (feature on/off) with `--coverage`, runs the tests, invokes `gcov -f`, and computes `D_f`.
- **Required:** `cc`/`gcc`, `make`, `gcov` (or `llvm-cov`), `python3` ≥ 3.9.
- **Optional:** `cmake` (CMake targets), `cargo` + `cargo-llvm-cov` (Rust targets), Docker
  (demos, KLEE), `boofuzz` (fuzzing), `klee` or the `klee/klee` image (symbolic tests).

Check the local toolchain with:

```bash
prat doctor
prat doctor App/mosquitto
```

### Coverage tooling substitution

The paper states the prototype uses `gcov` for C/C++ and `kcov` for Rust. C/C++ uses `gcov`.
**Rust uses `cargo-llvm-cov`, not `kcov`.** `cargo-llvm-cov` is the maintained source-based
coverage path for current stable Rust and works on the toolchains the demos pin; `kcov` is a
DWARF/breakpoint-based tool that is unmaintained for recent Rust and unavailable on some target
platforms. The lcov output is converted to PRAT's gcov representation, so the mapping algorithm is
identical across languages — only the instrumentation differs.

---

## 4. Evaluation targets

The paper evaluates seven codebases. Six are covered by demos (Mosquitto twice):

| # | Demo | Project / pinned version | Build | Feature analyzed | Paper value |
|---|---|---|---|---|---|
| 1 | `mosquitto-tls` | Mosquitto v2.0.15 | make | `TLS` | **790** LOC |
| 2 | `mosquitto-bridge` | Mosquitto v2.0.15 | make | `Bridge` | **640** LOC |
| 3 | `ffmpeg-dca` | FFmpeg n5.1.4 | autotools | `decoder=dca` | none published |
| 4 | `uamqp-websockets` | azure-uamqp-c | cmake | `use_wsio` | **26** LOC |
| 5 | `opendds-content-filtered-topic` | OpenDDS DDS-3.25 | MPC | `content-filtered-topic` | **73** LOC |
| 6 | `quiche-qlog` | quiche 0.20.1 | cargo | `qlog` | none published |
| 7 | `aom-encoder` | libaom v3.7.1 | cmake | `CONFIG_AV1_ENCODER` | none published |

**rav1e is not covered by a demo.** The generic Cargo adapter can drive it
(`./scripts/fetch-targets.sh rav1e`), but it is not one of the bundled pinned demos, so this
artifact covers six of the paper's seven codebases.

### Where a demo analyzes something the paper did not

Two substitutions are genuine and unavoidable; one previous substitution was not, and has been
reverted to a real paper feature.

**FFmpeg: `decoder=dca` instead of `x264`.** x264's removable code lives in the external
`libx264` library, which FFmpeg only links. PRAT compiles the in-tree wrapper
(`libavcodec/libx264.c`, ~549 lines), so it cannot measure x264's footprint at all. `decoder=dca`
is a self-contained in-tree decoder (7 dedicated files) and exercises the autotools path
properly. The paper reports no per-feature FFmpeg value, so nothing is lost by the substitution
and nothing is claimed for it.

**quiche: `qlog` instead of `ffdhe`.** `ffdhe` (finite-field Diffie-Hellman) is a BoringSSL TLS
setting, not a Cargo feature in any quiche release, so `cargo build --features ffdhe` fails with
"none of the selected packages contains these features". `qlog` is a real Cargo feature with ~63
`#[cfg(feature = "qlog")]` sites exercised by the crate's own tests. Again, the paper reports no
per-feature quiche value.

**OpenDDS: `content-filtered-topic`, replacing `SECURITY`.** `SECURITY` is not one of the paper's
OpenDDS features and had no published value, which is why its result had nothing meaningful to be
compared against. The paper's five OpenDDS features — `persistence-profile`,
`ownership-kind-exclusive`, `query-condition`, `content-filtered-topic`, `ownership-profile` — are
all real DDS-3.25 `./configure` switches. `content-filtered-topic` is now the demo target, so this
codebase has a published value (73 LOC) to validate against.

### Naming corrections

`use_wsio` is the option the paper reports for azure-uamqp-c WebSocket support. `USE_WEBSOCKETS`
appeared in earlier revisions of this repo; it is neither a CMake variable in that codebase nor the
paper's name for the option. Demo metadata now records the feature that is actually analyzed, so
`demo_manifest.json` no longer names an unanalyzed feature.

---

## 5. Running and validating

```bash
make setup                       # venv + PRAT + dev deps

# Single feature
prat App/mosquitto TLS
prat App/mosquitto TLS --remove  # removes, rebuilds, re-runs the tests

# Algorithm 1 over every discovered feature (n+1 builds)
prat App/mosquitto --batch

# Feature identification only
prat App/mosquitto --list --verbose

# Symbolic tests in T (paper Table 3 parameters; needs KLEE)
prat App/mosquitto TLS --symbolic

# The paper's cumulative variant chain, fuzzed (needs boofuzz)
pip install 'prat[fuzz]'
prat App/mosquitto --variants 8 --fuzz --fuzz-seconds 600

# Docker demos
make paper-check                 # build → run → remove image, per demo, then validate
prat reproduce mosquitto-tls
prat reproduce --all

# Validate whatever has run
python3 scripts/validate_paper_results.py results/docker/ \
    --json results/validation_report.json
```

### How the validator scores

| Status | Meaning |
|---|---|
| `PASS` | The paper publishes a value for this feature and `\|D_f\|` is within the accepted range |
| `FAIL` | The paper publishes a value and `\|D_f\|` is outside the range |
| `OBSERVED` | The paper publishes **no** value for the feature analyzed; the measurement is reported and not scored |
| `MISSING` | No result file found for the target |
| `ERROR` | The demo ran but the workflow did not succeed |

Tolerances are wide and deliberately so. The paper's per-feature numbers come from
KLEE-generated tests over a 60-minute budget against the codebase versions available in 2021; a
local run uses whatever tests ship with the pinned version and, unless `--symbolic` is passed and
KLEE is present, no symbolic tests at all. Since the mapping is bounded by the coverage `T`
achieves, a narrower `T` yields a smaller `D_f`. Expect results at the lower end of each range
without KLEE, and expect version drift in both directions on codebases whose pinned tag is years
newer than the paper's.

Tolerances have not been widened to accommodate any particular measurement; they express the
methodological gap above.

---

## 6. What a reviewer should check

Rather than trusting a results table, these are checkable directly:

**The mapping computes the paper's quantity.** `src/tests/test_mapping.py` asserts that a line
executed only when the feature is on is removed, a line executed with the feature off is kept, and
a line never executed in either build is kept. `src/tests/test_integration.py` does the same
against a real compiler and real gcov, then removes the code and rebuilds.

**Algorithm 1 performs n+1 builds.** `src/tests/test_batch.py::TestAlgorithmOneBuildCount`
asserts the build count and that the baseline enables everything while each subsequent build
leaves exactly one feature off. `BatchResult.builds_performed` reports it at runtime.

**The build gate actually gates.** `src/tests/test_removal.py::TestBuildGate` asserts that a
failed rebuild fails the removal and restores the tree.

**The balance guard is load-bearing.** `TestGuardPreservesCompilation` compiles the result of a
guarded removal and shows the same removal without the guard fails to compile.

**The feature graph is the paper's DAG.** `src/tests/test_feature_graph.py::TestGraphInvariants`
asserts the three tiers, contiguous-line merging, acyclicity, and that a range shared by two
features is a single vertex.

**Feature identification matches the paper's criteria.** `src/tests/test_discovery.py` covers the
BOOL rule, the autoconf "feature"/"optional" description filter, Cargo's non-default rule, the
`WITH_*` Make toggles, and the spurious/developer-option filtering.

```bash
make test        # full suite
make lint        # ruff
make typecheck   # mypy
```

---

## 7. Known limitations

- **Dynamic analysis is bounded by the test suite.** `D_f` only contains lines `T` actually
  executed. Without KLEE, `T` is the project's own tests and `D_f` is correspondingly smaller.
  `ExtractionResult.excluded_never_executed` reports how many executable lines were left in place
  for this reason, so the completeness cost is visible rather than silent.
- **rav1e has no demo** (see §4).
- **Rust coverage uses `cargo-llvm-cov`, not `kcov`** (see §3).
- **KLEE requires its own environment.** `--symbolic` uses a local `klee` or the `klee/klee`
  image, and is skipped with a message when neither is present.
- **The all-features baseline can fail to compile** on codebases with mutually exclusive options.
  Batch analysis falls back to the project's default configuration and says so in
  `BatchResult.baseline_note`; `D_f` then isolates each feature against defaults rather than
  against a fully-featured build.
- **Fuzzing needs an instrumented broker.** `fuzz_variant` reports crash data without coverage
  instrumentation, but the coverage columns require a `--coverage` build.
- **Whole-program Table 4 comparison needs a full batch run** on each codebase, which is
  expensive; the bundled demos are per-feature.
