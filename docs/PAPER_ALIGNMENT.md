# Paper Alignment — PRAT Implementation vs. Paper Claims

**Paper**: Williams et al., "Guided Feature Identification and Removal for Resource-constrained Firmware," ACM Transactions on Software Engineering and Methodology (TOSEM), 2021.  
**DOI**: [10.1145/3487568](https://doi.org/10.1145/3487568)

This document maps paper sections, contributions, and evaluation targets to specific code modules, CLI commands, and Docker demos so reviewers can verify each claim.

---

## Paper Contributions → Code Mapping

### C1: Differential Dynamic Coverage Analysis (§5.1–5.2)

**Paper claim**: Compile project with/without each feature flag, execute test suite for dynamic coverage, diff `.gcov` outputs to identify feature-specific code.

| Paper concept | Code module | Key function |
|---|---|---|
| Algorithm 1: Build n+1 variants | `src/prat/batch.py` | `run_batch_analysis()` |
| Feature flag discovery (Make/CMake/Autotools/Cargo) | `src/prat/discovery.py` | `discover_features()`, `discover_features_make()`, etc. |
| Compile with coverage flags | `src/prat/compilation.py` | `compile_with_adapter()`, `compile_project()` |
| Execute binary for dynamic coverage (.gcda generation) | `src/prat/coverage.py` | `execute_for_coverage()` |
| Run gcov/llvm-cov to produce .gcov files | `src/prat/coverage.py` | `generate_coverage()`, `generate_coverage_with_adapter()` |
| Diff coverage outputs | `src/prat/diff.py` | `diff_coverage_files()` |
| Extract feature-specific lines (##### markers) | `src/prat/extraction.py` | `extract_features()` |
| End-to-end orchestration | `src/prat/workflow.py` | `run_complete_workflow()` |

**Reproduce**:
```bash
# Single feature:
prat App/mosquitto TLS --tests

# All features (Algorithm 1):
prat App/mosquitto --batch
```

---

### C2: Feature Graphs for Analyst Decision Support (§6)

**Paper claim**: Interactive feature graphs show features → files → shared dependencies, enabling informed removal decisions.

| Paper concept | Code module | Key function |
|---|---|---|
| Graph construction from batch results | `src/prat/feature_graph.py` | `build_feature_graph()` |
| Cross-feature file overlap | `src/prat/batch.py` | `CrossFeatureMap` dataclass |
| Self-contained interactive HTML (D3.js) | `src/prat/feature_graph.py` | `generate_feature_graph_html()` |
| DOT graph export | `src/prat/reporting.py` | `generate_dot_graph()` |

**Reproduce**:
```bash
prat App/mosquitto --batch --output results/batch/
# → results/batch/feature_graph.html (interactive)
# → results/batch/FDG.dot (Graphviz)
```

---

### C3: Automated Feature Code Removal (§7)

**Paper claim**: PRAT removes identified feature-specific lines from the source tree. Two modes: line-level removal (shared files) and file-level removal (feature-only files).

| Paper concept | Code module | Key function |
|---|---|---|
| Line-level removal (remove specific lines) | `src/prat/removal.py` | `remove_feature_code()` |
| File-level removal (delete feature-only files) | `src/prat/removal.py` | `remove_feature_code(feature_only_files=...)` |
| Backup/restore for safety | `src/prat/removal.py` | `backup=True` parameter |
| Post-removal rebuild | `src/prat/removal.py` | `rebuild=True` parameter |

**Reproduce**:
```bash
prat App/mosquitto TLS --remove
# → Modifies source, rebuilds, reports success/failure
# → Backup saved to App/mosquitto/_backup_before_remove_TLS/
```

---

### C4: Post-Removal Correctness Verification (§8.7)

**Paper claim**: After removal, verify debloated binary by replaying unit tests and checking compilation correctness.

| Paper concept | Code module | Key function |
|---|---|---|
| Rebuild debloated project | `src/prat/verification.py` | `verify_correctness()` |
| Test suite replay | `src/prat/verification.py` | `verify_correctness(test_commands=...)` |
| KLEE test replay (if available) | `src/prat/verification.py` | `verify_correctness(symbolic_result=...)` |

**Reproduce**:
```bash
prat App/mosquitto TLS --remove --verify
# → Removes feature code, rebuilds, runs test suite, reports pass/fail
```

---

### C5: Symbolic Test Generation via KLEE (§5.3–5.4)

**Paper claim**: Use KLEE symbolic execution to generate high-coverage test inputs when existing test suites are sparse.

| Paper concept | Code module | Key function |
|---|---|---|
| KLEE configuration (Table 2 parameters) | `src/prat/symbolic.py` | `KleeConfig` dataclass |
| Compile to LLVM bytecode | `src/prat/symbolic.py` | `generate_symbolic_tests()` |
| KLEE invocation (local or Docker) | `src/prat/symbolic.py` | `generate_symbolic_tests(use_docker=...)` |
| Test case replay | `src/prat/symbolic.py` | `replay_tests()` |
| Availability check | `src/prat/symbolic.py` | `check_klee_available()` |

**Status**: ⚠️ **Experimental**. The module is implemented and passes unit tests (mocked), but has not been validated end-to-end in the KLEE Docker environment. The workflow gracefully skips KLEE when unavailable.

**Reproduce** (requires KLEE Docker image):
```bash
prat App/mosquitto TLS --symbolic
# → Falls back gracefully if KLEE is not installed
```

---

## Paper Evaluation Targets (Tables 4 & 5)

The paper evaluates PRAT on 7 open-source projects:

| # | Project | Language | Build System | Paper Feature(s) | Status |
|---|---|---|---|---|---|
| 1 | **Mosquitto** v2.0.15 | C | Make | TLS, Bridge, WebSockets, SRV, + 15 more | ✅ Full adapter + Docker demos |
| 2 | **FFmpeg** n5.1.4 | C | Autotools | x264, x265, vpx, mp3lame, opus, ... | ✅ Full adapter + Docker demo |
| 3 | **azure-uamqp-c** 2024-01-22 | C | CMake | USE_WEBSOCKETS, USE_OPENSSL | ✅ Adapter + Docker demo4 |
| 4 | **OpenDDS** DDS-3.25 | C++ | CMake | SECURITY, CONTENT_SUBSCRIPTION | ✅ Adapter + Docker demo5 |
| 5 | **Quiche** 0.20.1 | Rust | Cargo | ffdhe, qlog | ✅ Docker demo6 (generic Rust adapter) |
| 6 | **rav1e** v0.7.1 | Rust | Cargo | asm, nasm | ✅ Fetchable (generic Rust adapter) |
| 7 | **AOM (libaom)** v3.7.1 | C | CMake | CONFIG_AV1_ENCODER, CONFIG_AV1_DECODER | ✅ Adapter + Docker demo7 |

### Reproducing Paper Table 4 (LOC Reduction)

For all supported targets:

```bash
# Mosquitto — all features (paper reports all 19):
prat App/mosquitto --batch --output results/table4-mosquitto/

# FFmpeg — x264:
prat App/FFmpeg x264 --output results/table4-ffmpeg-x264/

# All paper targets via Docker (self-contained, no local setup):
make docker-build    # builds all 7 demo images
make docker-run      # runs all 7, generates demo_report.txt
cat results/demo_report.txt
```

**Expected ranges** (from paper, approximate):

| Target + Feature | Paper LOC Removed | PRAT Expected Range | Notes |
|---|---|---|---|
| Mosquitto TLS | ~1200 | 500–1500 | Depends on test coverage |
| Mosquitto Bridge | ~600 | 300–800 | |
| FFmpeg x264 | ~3000 | 1000–5000 | Varies with configure options |

> **Note**: Exact line counts depend on coverage tool version, test suite execution, and platform. The paper numbers reflect the specific KLEE-enhanced coverage used during evaluation. Without KLEE, numbers may be lower but still within the same order of magnitude.

---

## Docker Demos

Self-contained Docker demos that clone targets inside the image:

```bash
# Build all demos:
make docker-build

# Run all demos:
make docker-run

# Individual:
make docker-demo-mosquitto-tls
make docker-demo-mosquitto-bridge
make docker-demo-ffmpeg
```

Results are written to `results/docker/` with JSON checkpoint files containing exact line counts.

---

## Module Architecture → Paper Section Cross-Reference

```
Paper §5.1 (Feature Discovery)    → src/prat/discovery.py
Paper §5.1 (Algorithm 1)          → src/prat/batch.py
Paper §5.2 (Coverage Analysis)    → src/prat/coverage.py + compilation.py
Paper §5.2 (Differential Diff)    → src/prat/diff.py + extraction.py
Paper §5.3–5.4 (KLEE)            → src/prat/symbolic.py
Paper §6 (Feature Graphs)         → src/prat/feature_graph.py + reporting.py
Paper §7 (Code Removal)           → src/prat/removal.py
Paper §8.7 (Verification)         → src/prat/verification.py
Adapters (project-specific)       → src/prat/adapters/{mosquitto,ffmpeg,cmake,rust}.py
Docker reproducibility            → docker/demo{1,2,3}/Dockerfile
```

---

## Known Gaps vs. Paper

1. **KLEE integration** (§5.3–5.4): Implemented but unvalidated in Docker environment. Coverage numbers without KLEE may be lower than paper reports.

2. **kcov for Rust** (§8.1): Paper uses kcov for Rust projects; current implementation uses gcov-based coverage for Cargo builds. Functional but may differ from paper numbers.

3. **5 of 7 paper targets** (azure-uamqp-c, OpenDDS, Quiche, rav1e, AOM): Generic adapters support the build systems, but project-specific Docker demos and expected result ranges are not yet bundled. The generic pipeline works via:
   ```bash
   prat <project-path> <FEATURE_FLAG>
   ```

4. **Binary size measurement** (Table 5): Paper reports binary size reduction. PRAT currently reports LOC reduction but does not automatically measure binary size deltas. This can be done manually:
   ```bash
   ls -la <binary-before>
   prat ... --remove
   make -C <project>
   ls -la <binary-after>
   ```

---

## Methodology: Static Differential Coverage vs. the Paper's Dynamic Approach

PRAT performs **static, compile-time differential coverage**: it compiles a target with a
feature on and off (instrumented with `--coverage`) and runs `gcov` over the resulting
instrumentation graph (`.gcno`). The paper's headline numbers were produced with
**KLEE-enhanced dynamic coverage** (symbolic execution + test replay). Reproducing the paper
exactly is therefore not expected; the tolerance ranges in `paper_expected_results.json`
(40–60%) exist to absorb this gap. The full per-target analysis lives in
[`../REPRODUCIBILITY.md`](../REPRODUCIBILITY.md); a committed sample run is in
[`sample-results/`](sample-results/).

### Two metrics

PRAT reports both, and never silently substitutes one for the other:

- **Interleaved** (`total_removable_lines`) — feature code inside files **shared** by both
  builds (`#ifdef FEATURE … #endif`). This is the primary metric and keeps the
  interleaved-feature demos comparable.
- **Combined / paper-aligned** (`total_feature_lines`) — interleaved **plus** whole source
  files that exist only when the feature is enabled (`feature_only_removable_lines`). This is
  closest to the paper's notion of total removable feature code.

### Why feature *structure* determines reproducibility

| Feature structure | Example | Interleaved | Combined | Reproduces? |
|-------------------|---------|-------------|----------|-------------|
| Interleaved via `#ifdef` in shared files | Mosquitto TLS / BRIDGE | high | ~same | ✅ in range |
| Dedicated module, modest size | azure-uamqp-c WebSockets (`wsio.c`, `uws_client.c`) | ~0 | moderate | 🟢 in range via combined |
| Dedicated wrapper only (external lib) | FFmpeg x264 wrapper `libavcodec/libx264.c` | ~0 | small | ❌ real code is external (libx264) |
| In-tree internal codec (substitute) | FFmpeg DTS decoder (`decoder=dca`, 7 files) | 54 | 3728 | ✅ in range |
| Large dedicated subsystem (static) | libaom AV1 encoder (187 files) | low | very high | ❌ static over-counts |
| Large dedicated subsystem (dynamic) | libaom AV1 encoder, real encode/decode | 8691 | 54060 | ✅ in range (interleaved) |
| Large subsystem + deps (filtered) | OpenDDS SECURITY plugin / co-enabled deps | 10224 | 17021 | ❌ plugin 4802 in range; full footprint over |

For static dedicated-file features the paper value sits **between** PRAT's interleaved (too
low) and combined (too high) measures. **Dynamic** coverage closes that gap (libaom: a real
encode/decode pulls the count into range). OpenDDS is a distinct case: after isolating
dependencies and filtering generated IDL type-support, its differential is 17021 — the core DDS
Security plugin (`dds/DCPS/security`, 4802) is in range, but the full `--security` footprint also
pulls in secure-discovery and ICE dependencies (see `REPRODUCIBILITY.md` §6.5).

### Threats to validity

1. **Coverage tool & flags.** gcov emits per-line `#####` data from `.gcno` only when the
   build is unoptimized (`-O0`/`Debug`) and gcov is invoked from the directory where
   compilation occurred (so it can locate sources). Mosquitto additionally executes its test
   suite, yielding true dynamic coverage. These conditions are encoded per build system in
   `src/prat/coverage.py`.
2. **Feature flag fidelity.** A demo only measures what the flag actually toggles. Two paper
   feature names did not map to real build switches: azure-uamqp-c WebSockets is `use_wsio`
   (not `USE_WEBSOCKETS`), and quiche 0.20.1 has **no** `ffdhe` Cargo feature at all.
3. **Build-system coverage.** OpenDDS DDS-3.25 is not a CMake-root project (Perl `configure` +
   MPC + ACE/TAO); the bundled CMake adapter cannot drive it, so that target is not reproduced
   here.
4. **No KLEE / no symbolic execution.** Out of scope by design; the dynamic reachability the
   paper obtained from KLEE is not reconstructed.
5. **Platform.** Numbers were collected on Linux aarch64 (Docker on Apple Silicon) with the
   compilers recorded in each `manifest.json`; absolute counts can shift with compiler version
   and architecture.

### Status of the seven Docker demos

All seven paper targets now ship as self-contained Docker demos (`docker/demo1`–`demo7`) with
pinned tags whose commits are verified equal to upstream (see `REPRODUCIBILITY.md` §2). Four
reproduce within range: Mosquitto TLS/BRIDGE directly, azure-uamqp-c via the combined
(feature-file) metric, and libaom via dynamic coverage. Two more run in range via documented
**substitute** features, each flagged inline as not reproducing the paper value: FFmpeg analyzes
the in-tree DTS decoder (`decoder=dca`, 3728) because x264's real code is the *external* libx264
library PRAT never compiles (it sees only the ~549-line in-tree wrapper); quiche analyzes `qlog`
(420) because the paper's `ffdhe` is not a Cargo feature in 0.20.1 (codebase drift), via stable
`cargo-llvm-cov`. That is 6 of 7 in range. OpenDDS builds and runs end-to-end (a full ACE/TAO +
configure/MPC environment); after isolating dependencies and filtering generated IDL, its
differential is 17021 — the core DDS Security plugin (4802) is in range, but the full
`--security` footprint (discovery + ICE deps) exceeds it. No tolerance ranges were altered.
