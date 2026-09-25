# Artifact Guide

This page is for a reviewer who has a copy of the repository and wants to know, in order:
what to run first, how long it takes, what "working" looks like, and where the evidence for
each paper claim lives. It states only what can be checked on this tree; see
[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the methodology and the provenance of every
paper number, and [`docs/PAPER_ALIGNMENT.md`](docs/PAPER_ALIGNMENT.md) for the claim-by-claim
mapping to code and tests.

**Paper:** Williams et al., *Guided Feature Identification and Removal for Resource-constrained
Firmware*, ACM TOSEM 2021, [doi:10.1145/3487568](https://doi.org/10.1145/3487568).

## What this artifact claims, and what it does not

PRAT implements the paper's pipeline: feature identification from build configurations,
feature-to-code mapping by differential dynamic coverage (`D_f = L_all \ L_f`, Algorithm 1),
feature graphs, source-level removal with a rebuild gate, and post-removal verification that
re-runs the same test set `T`. Every function and test named in the documentation exists, and
every number quoted as a paper value is traceable to a file under `paper/`.

It does **not** claim an exact numerical reproduction of the paper's tables. The paper does not
record the source revisions it measured, so the Docker demos analyse named later releases and
report a *compatibility* result: the evidence chain is complete and the algorithm behaved as
specified on that pinned commit. **No result files are committed**; every number a reviewer
reads is one they produced (see `results/README.md`).

## Path 1: trust the implementation (about one minute)

Requirements: Python 3.9+, a C compiler (`cc`), `gcov`, `make`. No Docker, no network beyond
`pip`.

```bash
make setup     # venv + PRAT + dev dependencies
make test      # full suite, about 25 seconds on a laptop
make lint      # ruff
make typecheck # mypy
```

**Success looks like:** every test passes (the count is printed; a handful of Boofuzz tests are
skipped if `boofuzz` is not installed), ruff reports `All checks passed!`, mypy reports
`Success: no issues found`.

The suite is not mocked around the parts that matter. `src/tests/test_integration.py` compiles a
small C project with a real compiler, runs it under real `gcov`, computes `D_f`, removes the
mapped lines, rebuilds, and re-runs the tests. The tests that pin each paper claim are listed in
`REPRODUCIBILITY.md` §6; the ones a sceptical reader should open first:

| Claim | Test |
|---|---|
| The mapping is Algorithm 1's set difference, and keeps never-executed lines | `src/tests/test_mapping.py` |
| Batch analysis performs n+1 builds against an all-features baseline | `src/tests/test_batch.py::TestAlgorithmOneBuildCount` |
| The single-feature path builds `B_all` vs `B_f`, and runs one `T` against both | `src/tests/test_workflow.py::TestAlgorithmOneBaseline` |
| A failed rebuild fails the removal and restores the tree | `src/tests/test_removal.py::TestBuildGate` |
| Verification re-runs `T` and reproduces every pre-removal outcome | `src/tests/test_verification.py::TestReferenceOracle` |
| KLEE parameters match Table 3 | `src/tests/test_symbolic.py` |

## Path 2: run the pipeline on a real target (minutes, Docker)

Requirements: Docker with about 8 GB free disk. Each demo builds an image containing one paper
codebase at a pinned tag, discovers its feature set, builds `B_all` and `B_f` with coverage
instrumentation, runs the fixed `T` against both, maps `D_f`, removes it, rebuilds, and verifies.

The two Mosquitto demos are the ones with published per-feature values and the fastest builds:

```bash
make paper-check-fast
```

This builds and runs `mosquitto-tls` and `mosquitto-bridge` (2–5 minutes each after the image
is built), deletes each image afterwards, and runs the validator in strict mode over the two
results, writing `results/mosquitto-validation-report.json`.

**Success looks like:** the validator prints one row per target with status `COMPATIBLE`, the
observed `|D_f|`, and the paper's value (790 for TLS, 640 for Bridge) with the deviation. Strict
mode fails a target unless the run recorded `baseline_mode = "all-features"`, executed the same
`T` against both builds, verified the pinned source commit, removed the mapped lines, rebuilt,
and passed post-removal verification. A deviation from the paper's value is reported, not
scored: the paper's own source revision is unrecorded, so no acceptance band is applied unless
one is configured in `paper_expected_results.json` (none currently is).

The full corpus, all eight demos over the seven paper codebases:

```bash
make compatibility-check          # one to two hours of demo runtime plus image builds; images are removed as it goes
```

Four of the eight demos analyse a feature the paper publishes no line count for; the validator
reports those as `OBSERVED`, never as a pass or a fail.

**Known caveat.** The single-feature baseline was changed from project-defaults-±f to `B_all` vs
`B_f` in this revision. A local run on macOS (`prat App/mosquitto TLS --remove` with the options
this platform cannot build skipped via `--skip-feature`) exercised the whole path: `B_all` over 19
options, the fixed seven-session `T` (plain, TLS publish/subscribe, mutual TLS, a cipher/version/
ALPN session, three expected-failure probes) against both builds, `|D_TLS| = 600` lines across
12 files. Exact removal succeeded: 501 lines removed, 0 declined, 99 kept for a disclosed reason
(8 delimiter-only lines shared code still needs, 91 guards of shared code the reduced build
compiles but never executed, which the paper's correctness rule forbids removing). The debloated
tree rebuilt, the plain session passed unchanged, and the six TLS sessions failed exactly as they
did against the pre-removal `B_TLS` reference (`expected_failures`). The Docker images, which run
Mosquitto's unit tests as `T`, have not been rebuilt on our side since the change; their
Dockerfiles install the libraries `B_all` needs. If a target's all-features configuration does
not compile in its image, the demo fails with `Compilation failed (B_all)` rather than silently
falling back to another baseline. That is the intended behaviour; report it rather than working
around it.

## Path 3: the full paper algorithm on one codebase (hours, optional)

```bash
make fetch-mosquitto
prat App/mosquitto --paper-algorithm --output results/mosquitto-paper
make validate-batch CHECKPOINT=results/mosquitto-paper/batch_checkpoint.json
```

`--paper-algorithm` requires KLEE (locally or via the `klee/klee` image) and runs it for the
paper's 60 minutes, builds `B_all` plus one `B_f` per discovered feature, removes the union of
every `D_f`, and verifies. `validate_batch_results.py --strict` checks the checkpoint recorded
n+1 builds, an all-features baseline, one test plan, and a passed verification.

## Where the evidence lands

Each run writes, under its output directory:

| File | What it is |
|---|---|
| `workflow_checkpoint.json` / `batch_checkpoint.json` | The run's full record: `baseline_mode`, the exact feature configuration of every build (`mapping_build_states`), the test plan digest and size (`test_plan_id`, `test_plan_commands`), whether both builds ran the same plan (`test_plan_identical`), which tests of `T` could not run against `B_f` (`tests_not_run_in_b_f`), coverage percentages, `|D_f|`, removal and verification results |
| `manifest.json` (demos) | Source commit, tool versions, platform, and the same baseline and test-plan fields |
| `report.html`, `report.json`, `FDG.dot` | The mapping: removable lines per file, with inline source |
| `feature_graph.html` | The paper's three-tier feature graph (feature → files → line sets), interactive and fully offline (D3 is inlined). Open this first to see *what* `D_f` is before reading the removal result |
| `comparison_reports/` | The paper's side-by-side reports: per-line coverage state in both builds with `D_f` marked, and original versus debloated source |

## Reading a verification result

Verification re-runs the fixed `T` against the debloated build and compares each command's
outcome with the one recorded against the pre-removal build in the same configuration.

- `PASSED`: every outcome reproduced. Tests of the removed feature that failed before removal
  and failed identically after it are listed as `expected_failures`; they are preserved
  behaviour and do not count against the pass rate.
- `FAILED`: some outcome changed. A test that now passes where it failed, fails where it
  passed, prints something different, or can no longer be started is listed in
  `diverged_suites`.
- `CRASHED`: a test was killed by a signal that the reference run did not produce. A crash the
  reference also produced is listed in `preexisting_crashes` and does not fail verification.
- `INCONCLUSIVE`: the debloated tree compiled but no test was available. This is not a pass.

## What is still open

- The `B_all` builds inside the eight pinned Docker images have not been re-run since the
  baseline correction (see the caveat under Path 2).
- The paper's Table 4 whole-program totals require a full `--paper-algorithm` run per codebase,
  which the bundled demos do not perform.
- Rust coverage uses `cargo-llvm-cov` rather than the paper's `kcov`
  (`REPRODUCIBILITY.md` §3).
