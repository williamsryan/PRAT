# PRAT Revival Roadmap

> Historical planning note: this file records the staged recovery plan for the
> research prototype. For current release-readiness status, see
> `docs/RELEASE_AUDIT.md`.

**Goal**: Bring PRAT from its current ~40% paper-fidelity state to a fully functional, demonstrable, shareable tool that faithfully implements the claims of the ACM TOSEM 2021 paper.

**Paper**: "Guided Feature Identification and Removal for Resource-constrained Firmware" — Williams et al., doi:10.1145/3487568

---

## ⚠️ Status: Phase 1 Implementation Complete (2026-04-17)

Phase 1 code is written and parseable. 96 tests defined across 9 files.
**Next step**: Run `pytest -v` to validate, then begin Phase 2.
Paper fidelity: ~70% (up from ~45%).

---

## What's Already Done (Today's Session)

- [x] **Cleanup**: Archived legacy code, purged `__pycache__`, added `.gitignore`
- [x] **Packaging**: `pyproject.toml`, `scripts/fetch-targets.sh`, updated README
- [x] **Plumbing**: Fixed 6 call-signature mismatches, wired reporting into workflow
- [x] **Adapters**: `get_adapter()` factory, `compile_with_adapter()`, `generate_coverage_with_adapter()`, wired into workflow Steps 2–5
- [x] **Tests**: 80 unit tests across 7 test files, all modules covered
- [x] **Reports**: Modern self-contained HTML, project-agnostic DOT, new JSON output
- [x] **Paper analysis**: Full gap analysis against all 6 paper contributions
- [x] **Phase 1**: Dynamic coverage, code removal, batch mode (96 tests across 9 files)

---

## Phase 1: Fix the Core Algorithm ✅ COMPLETE

*Make the tool do what the paper actually describes: dynamic coverage from test execution, not just compile-time reachability.*

### 1.1 Dynamic Coverage via Test Execution ✅
**Paper §5.2**: Coverage comes from *executing* the binary under test cases, not from compiling.

| Task | File(s) | Effort |
|---|---|---|
| Add `execute_tests()` step that runs binary + captures `.gcda` files | `coverage.py` | 4h |
| After compilation, execute test suite (if available) before running gcov | `workflow.py` | 2h |
| Adapter method `get_execution_command()` — how to run the binary to exercise features | `adapters/base.py`, all adapters | 3h |
| Update `generate_coverage()` to require `.gcda` files exist before generating `.gcov` | `coverage.py` | 1h |

**Acceptance**: Running `workflow.py` on Mosquitto with `--tests` produces coverage from *executing* the test suite, not just from compilation. `.gcda` files present before gcov runs.

### 1.2 Actual Code Removal ✅
**Paper §7**: PRAT removes identified lines from source and rebuilds.

| Task | File(s) | Effort |
|---|---|---|
| New `removal.py` module: `remove_feature_code(extraction_result, project_path) → RemovalResult` | New file | 4h |
| Line-level removal: comment out or delete `#####`-marked lines | `removal.py` | 3h |
| File-level removal: delete files that exist only in feature-enabled build | `removal.py` | 1h |
| Post-removal rebuild to verify compilation succeeds | `removal.py` | 2h |
| `--remove` flag on CLI, Step 9 in workflow | `workflow.py`, `prat_cli.py` | 1h |
| Tests for removal module (mock filesystem ops) | `tests/test_removal.py` | 2h |

**Acceptance**: `run_complete_workflow("App/mosquitto", "TLS", remove=True)` produces a modified source tree that compiles successfully without TLS support.

### 1.3 Multi-Feature Batch Mode ✅
**Paper §5.1 (Algorithm 1)**: Build n+1 versions — all-features baseline + one-per-feature-disabled.

| Task | File(s) | Effort |
|---|---|---|
| New `batch.py` module: `run_batch_analysis(project_path) → BatchResult` | New file | 4h |
| Discovers all features, builds baseline, then per-feature coverage diffs | `batch.py` | 3h |
| Aggregate results into cross-feature dependency map | `batch.py` | 2h |
| CLI: `prat --batch App/mosquitto` | `prat_cli.py` | 1h |

**Acceptance**: `run_batch_analysis("App/mosquitto")` produces a report covering all 19 Mosquitto features with cross-feature file overlap data.

---

## Phase 2: Feature Graphs & Interactive Visualization ⏱️ 2–3 days

*Paper Contribution C2: "user-friendly feature graphs" for analyst decision-making.*

### 2.1 Interactive Feature Graph
**Paper §6**: Feature graphs show features → files → shared code dependencies.

| Task | File(s) | Effort |
|---|---|---|
| New `feature_graph.py`: build graph data structure from batch results | New file | 3h |
| Cross-feature analysis: which files are shared between features | `feature_graph.py` | 2h |
| Self-contained HTML visualization (D3.js or similar, embedded) | `reporting.py` | 6h |
| Interactive: click feature to highlight affected files, hover for line counts | `reporting.py` | 3h |
| Feature selection UI: checkboxes to select features for removal | `reporting.py` | 2h |

**Acceptance**: Running batch mode generates an `index.html` that shows an interactive graph where clicking "TLS" highlights `net.c`, `tls_mosq.c`, etc., and shows line counts.

---

## Phase 3: KLEE / Symbolic Test Generation ⏱️ 5–7 days

*Paper Contribution C1/C5: Symbolic execution for high-coverage test generation.*

### 3.1 KLEE Integration
**Paper §5.3–5.4**: Compile to LLVM bytecode → run KLEE → replay tests.

| Task | File(s) | Effort |
|---|---|---|
| New `symbolic.py` module with KLEE pipeline | New file | 6h |
| LLVM bytecode compilation step (clang → .bc) | `symbolic.py` | 3h |
| KLEE invocation with configurable parameters (Table 2 from paper) | `symbolic.py` | 4h |
| Test case replay via `klee-replay` | `symbolic.py` | 3h |
| Docker image with KLEE pre-installed | `docker/klee/Dockerfile` | 4h |
| Integration into workflow: auto-generate tests if no unit tests available | `workflow.py` | 2h |
| Fallback: if KLEE unavailable, use AFL/libFuzzer for coverage generation | `symbolic.py` | 4h |

**Acceptance**: `run_complete_workflow("App/mosquitto", "TLS", symbolic=True)` generates KLEE test cases, replays them, and produces coverage data with higher fidelity than compilation-only.

**Note**: KLEE requires LLVM 9/11 + specific build environment. Docker-based execution is the practical path. Consider offering AFL-based fuzzing as a lighter alternative that doesn't require KLEE infrastructure.

---

## Phase 4: Correctness Verification ⏱️ 3–4 days

*Paper §8.7: Verify debloated binaries don't introduce bugs.*

### 4.1 Post-Removal Testing
| Task | File(s) | Effort |
|---|---|---|
| New `verification.py`: run unit tests on debloated binary | New file | 3h |
| AFL fuzzing harness: fuzz debloated binary for crash detection | `verification.py` | 4h |
| Branch coverage measurement on debloated binary | `verification.py` | 2h |
| Comparison report: original vs. debloated binary (size, coverage, test pass rate) | `reporting.py` | 3h |
| Integration into workflow as optional Step 10 | `workflow.py` | 1h |

**Acceptance**: After feature removal, PRAT runs the test suite on the modified binary and reports pass/fail rate + branch coverage %.

---

## Phase 5: Evaluation Reproducibility ⏱️ 3–5 days

*Reproduce Tables 4 and 5 from the paper.*

### 5.1 Expand Target Projects
| Task | Effort |
|---|---|
| Add azure-uamqp-c, OpenDDS, Quiche, rav1e, AOM to `fetch-targets.sh` | 2h |
| Write adapters for azure-uamqp-c (CMake), AOM (CMake) | 4h |
| Docker demos for all 7 targets | 6h |
| Reproduce Table 4: LOC + binary size (all features / manual / PRAT) | 8h |
| Reproduce Table 5: PRAT vs. Piece-wise comparison | 6h |

**Acceptance**: Running all 7 demos produces a comparison table matching the paper's Table 4 numbers (within reasonable tolerance for version differences).

---

## Phase 6: Polish & Share ⏱️ 2–3 days

### 6.1 Documentation & CI
| Task | Effort |
|---|---|
| Rewrite docs/API.md, EXAMPLES.md for new capabilities | 3h |
| GitHub Actions CI: lint (ruff) + test (pytest) + Docker build | 3h |
| `CONTRIBUTING.md` with architecture overview for teammates | 2h |
| Type annotations + `mypy --strict` pass | 3h |
| CLI help text and `--help` output polished | 1h |

### 6.2 Rust Coverage (kcov)
**Paper §8.1**: Uses `kcov` for Rust, not gcov.

| Task | Effort |
|---|---|
| Add `kcov` support to `coverage.py` for Cargo builds | 3h |
| Update RustAdapter to use kcov | 1h |
| Docker image with kcov for Rust demos | 2h |

---

## Timeline Summary

| Phase | Focus | Effort | Paper Fidelity After |
|---|---|---|---|
| **Done** | Cleanup, plumbing, tests, reports | ✅ Complete | ~45% |
| **Phase 1** | Core algorithm (dynamic coverage, removal, batch) | 3–4 days | ~70% |
| **Phase 2** | Interactive feature graphs | 2–3 days | ~80% |
| **Phase 3** | KLEE / symbolic test generation | 5–7 days | ~90% |
| **Phase 4** | Correctness verification | 3–4 days | ~95% |
| **Phase 5** | Evaluation reproducibility (7 targets) | 3–5 days | ~100% |
| **Phase 6** | Polish, CI, Rust kcov, docs | 2–3 days | 100% + shareable |

**Total**: ~19–26 working days for full paper fidelity.
**Minimum viable for sharing**: Phase 1 (~4 days) — gives you dynamic coverage + actual code removal + batch mode. That's the core value prop.

---

## Decision Points

**After Phase 1**, you can share PRAT as a working tool with honest caveats ("no symbolic test gen yet, no fuzzing verification"). The core differential coverage → identify → remove pipeline will be functional.

**Phase 3 (KLEE)** is the hardest and most environment-dependent. Consider whether symbolic test generation is essential for your use case, or if AFL-based fuzzing is a sufficient alternative. KLEE requires specific LLVM versions and a Docker-based workflow. If your teammates don't need KLEE specifically, an AFL harness in Phase 4 covers the "automated test generation" claim more practically.

**Phase 5 (Evaluation)** is only needed if you're reproducing the paper's specific numbers. For sharing as a tool, Phases 1–2 + 6 is the sweet spot.
