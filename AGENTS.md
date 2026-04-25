# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What PRAT Is

PRAT (Protocol Representation and Analysis Toolkit) implements compile-time differential coverage analysis to identify feature-specific code in C/C++/Rust projects. Given a project and a named feature (e.g., TLS), it compiles the project twice — once with the feature enabled and once disabled — captures gcov/llvm-cov coverage from both builds, diffs the results, and reports which lines are only executed when the feature is active. Optionally it removes those lines from source and verifies the debloated binary still passes tests. The technique is from: *"Guided Feature Identification and Removal for Resource-constrained Firmware"* (ACM TOSEM 2021, Williams et al.).

## Commands

```bash
# Install (editable, with dev deps) — use a venv on macOS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Fetch target projects (Mosquitto, FFmpeg)
./scripts/fetch-targets.sh
./scripts/fetch-targets.sh mosquitto   # single target

# Run tests
pytest                                 # all 96 tests
pytest src/tests/test_workflow.py      # single file
pytest -k "test_name"                 # single test by name

# Type checking & linting
mypy src/prat/
ruff check src/

# CLI usage
prat App/mosquitto TLS                 # analyze a feature
prat App/mosquitto --list              # list discovered features
prat App/mosquitto TLS --dry-run       # preview without modifying
prat App/mosquitto TLS --tests         # include test-suite replay

# Docker demos
python3 src/demo-runner.py --build mosquitto-tls
python3 src/demo-runner.py --run-all --output demo_output
```

## Architecture

### Pipeline (workflow.py)

The core algorithm runs as a sequential pipeline; `run_complete_workflow()` orchestrates all steps, and `resume_workflow()` can restart from a saved `WorkflowCheckpoint`:

1. **discovery.py** — auto-detect available features from build configs (CMake `option()`, Autotools `--enable/--disable`, Make `WITH_*`, Cargo features)
2. **compilation.py** — compile twice (feature on / feature off) with gcov instrumentation; auto-detects build system; delegates to adapters
3. **coverage.py** — run tests/workload, invoke gcov or llvm-cov, collect `.gcov` files into `coverage_files_WITH_{FEATURE}_{yes|no}/`
4. **diff.py** — match `.gcov` files by basename, produce unified diffs in `diff_{FEATURE}/`
5. **extraction.py** — parse diffs for `#####` (never-executed) markers; emit per-file line lists in `ExtractionResult`
6. **reporting.py** — generate HTML tables, side-by-side diffs, DOT graphs, JSON
7. **removal.py** *(optional)* — delete or comment identified lines; backs up originals for `restore_from_backup()`
8. **verification.py** *(optional)* — rebuild debloated binary and replay test suite

### Adapters (src/prat/adapters/)

The adapter pattern isolates project-specific build logic. `get_adapter(project_path)` auto-detects and returns the right subclass of `ProjectAdapter` (base.py). Each adapter implements:
- `get_build_commands(feature, enabled, with_coverage)` — ordered list of build commands (default: `[get_compile_command(...)]`; FFmpeg overrides with `[configure, make]`)
- `get_compile_command(feature, enabled, with_coverage)` — primary build command
- `format_feature_flag(feature, enabled)` — e.g. `WITH_TLS=no`
- `get_test_command()`, `get_clean_command()`, `get_execution_commands()`
- `build_system` and `coverage_tool` properties

Current adapters: `mosquitto.py`, `ffmpeg.py`, `cmake.py`, `rust.py`. Add new projects here.

### Other Key Modules

| Module | Purpose |
|---|---|
| `batch.py` | Run all features in a project; builds `CrossFeatureMap` (file→features, feature→files, shared code) |
| `feature_graph.py` | Builds interactive HTML graph of feature↔file dependencies from batch results |
| `symbolic.py` | Compiles to LLVM bitcode, runs KLEE to generate higher-coverage test cases; optional Docker execution |
| `environment.py` | Verifies required external tools (gcc/clang, gcov/llvm-cov, make/cmake, etc.) at startup |
| `docker_runner.py` | Builds and runs demo containers for reproducible end-to-end demos |
| `cli.py` | Click-based entry point; all user-facing flags; `ProgressIndicator` for feedback |

### Result Dataclasses

Every module function returns a typed dataclass (`CompilationResult`, `CoverageResult`, `ExtractionResult`, `WorkflowResult`, etc.). Callers chain these results through the pipeline without unstructured dicts.

### Result Dataclasses

Every module function returns a typed dataclass (`CompilationResult`, `CoverageResult`, `ExtractionResult`, `WorkflowResult`, etc.). Callers chain these results through the pipeline without unstructured dicts.

### Test Layout

158 unit tests in `src/tests/`, one file per module (e.g., `test_compilation.py` ↔ `compilation.py`). Tests are configured via `pyproject.toml` (`testpaths = ["src/tests"]`, `addopts = "-v --tb=short"`).

## Known Limitations / Implementation Notes

- **`resume_workflow()`** — not yet implemented; currently reruns the full workflow. The checkpoint JSON still records which step failed and is useful for debugging.
- **`feature_graph.html`** — requires internet access (loads D3.js from `cdn.jsdelivr.net`). The summary HTML report and DOT graph have no external dependencies.
- **Coverage tool on macOS** — `llvm-cov-9` is Ubuntu-specific. The Mosquitto adapter hardcodes it; on macOS, set up a symlink or use `gcov`. The dependency check requires at least one of `gcov` or `llvm-cov-9`.
- **FFmpeg build** — is a two-step process (`configure` then `make`). The FFmpeg adapter's `get_build_commands()` handles this; the generic `compile_project()` path also handles it via `_compile_autotools()`.
