# PRAT — Protocol Representation and Analysis Toolkit

[![CI](https://github.com/williamsryan/PRAT/actions/workflows/ci.yml/badge.svg)](https://github.com/williamsryan/PRAT/actions/workflows/ci.yml)
[![DOI](https://img.shields.io/badge/DOI-10.1145%2F3487568-blue.svg)](https://doi.org/10.1145/3487568)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

PRAT is the research artifact accompanying the paper *"Guided Feature Identification and Removal
for Resource-constrained Firmware"* (ACM TOSEM, 2021). It identifies and removes feature-specific
code from C/C++/Rust projects by **differential dynamic coverage analysis**: it builds a project
with and without each feature, runs a test suite against both, and attributes to the feature the
lines that execute only when it is enabled.

> 📚 If you use PRAT in academic work, please [cite the paper](#citation).

The paper does not publish the exact source revisions or its original artifact.
The Docker corpus therefore pins exact commits from later releases and checks whether the
implementation behaves consistently on every paper codebase. It is a compatibility
evaluation, not a claim that modern-version line counts exactly reproduce the 2021 run.

## How It Works

PRAT implements Algorithm 1 of the paper. For a program `P` with features `F`:

1. **Identify features** by parsing build configurations (Make, CMake, autoconf, Cargo)
2. **Assemble the test suite** `T = U u S` — the project's own tests plus tests generated
   by KLEE. Normal analysis may run with `U` alone; `--paper-algorithm` requires KLEE.
3. **Build the baseline** `B_all` with every feature enabled and collect the executed line set
   `L_all` by running `T` against it
4. **For each feature `f`**, build `B_f` with all features except `f`, collect `L_f`, and compute

   ```
   D_f = L_all \ L_f
   ```

   the lines that execute when `f` is on and do not when `f` is off. This is `n+1` builds for
   `n` features, not `2n`.
5. **Present** `D_f` as a *feature graph* — a DAG whose roots are features, intermediate nodes
   are source files, and leaves are contiguous runs of lines — so an analyst can see how much
   code each feature carries and where, before deciding
6. **Remove** the selected features' lines, rebuild, and re-run `T`, checking for crashes and
   for divergence from pre-removal behaviour

The mapping is a **set difference over executed lines**, not a textual diff. A line never
executed in either build is never removed: the paper trades completeness for soundness, so
incomplete test coverage shrinks `D_f` rather than pulling in unrelated code. How much was left
in place for that reason is reported on every run.

## Quick Start

### Prerequisites

- Python 3.9+
- Docker (for reproducible demos)
- Build tools: gcc, make, cmake
- Coverage tools: gcov or llvm-cov

### Installation

```bash
git clone <repository-url>
cd PRAT
pip install -e ".[dev]"
```

### Fetch Target Projects

Target projects (Mosquitto, FFmpeg) are not vendored in the repo. Fetch them with:

```bash
./scripts/fetch-targets.sh          # All targets
./scripts/fetch-targets.sh mosquitto  # Just Mosquitto
./scripts/fetch-targets.sh ffmpeg     # Just FFmpeg
```

### Running PRAT

#### Using the Workflow API (Recommended)

```python
from prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS",
    run_tests=False
)

print(f"Removable lines: {result.extraction_result.total_removable_lines}")
```

#### Using the CLI

```bash
# Analyze a feature
prat App/mosquitto TLS

# List available features
prat App/mosquitto --list

# Dry run (preview operations)
prat App/mosquitto TLS --dry-run

# With test suite
prat App/mosquitto TLS --tests --verbose

# Enforce Algorithm 1 end to end, including KLEE, union removal, and verification
prat App/mosquitto --paper-algorithm
```

The KLEE stage currently supports C/C++ LLVM bitcode. Cargo/Rust projects support
dynamic differential mapping and fail explicitly if symbolic or full-paper mode is requested.

#### Using Docker Demos

```bash
# Build and run a demo
python3 src/demo-runner.py --build mosquitto-tls
python3 src/demo-runner.py --run mosquitto-tls --output demo_output

# Run all demos with comparison report
python3 src/demo-runner.py --run-all --output demo_output
```

## Architecture

```
src/prat/
├── workflow.py        # End-to-end orchestration with checkpoints
├── batch.py           # Multi-feature batch analysis (paper Algorithm 1)
├── discovery.py       # Automatic feature flag discovery
├── compilation.py     # Multi-build-system compilation (Make, CMake, Autotools, Cargo)
├── coverage.py        # gcov/llvm-cov/cargo-llvm-cov coverage generation
├── gcov.py            # gcov parsing: executed / never-executed / non-executable line sets
├── mapping.py         # D_f = L_all \ L_f (paper Algorithm 1, lines 9-11)
├── diff.py            # Side-by-side code comparison reports
├── extraction.py      # Packages D_f for reporting and removal
├── removal.py         # Automated feature code removal (line- and file-level)
├── verification.py    # Post-removal correctness verification
├── symbolic.py        # KLEE symbolic test generation (paper Table 3 parameters)
├── variants.py        # Cumulative variant chain for the correctness evaluation
├── fuzzing.py         # Boofuzz MQTT harness (optional: pip install 'prat[fuzz]')
├── feature_graph.py   # Three-tier feature-graph DAG + interactive D3.js view
├── reporting.py       # HTML report + DOT graph generation
├── docker_runner.py   # Docker container orchestration
└── adapters/          # Project-specific build adapters
    ├── base.py        # Abstract adapter interface
    ├── mosquitto.py   # Mosquitto MQTT broker (Make)
    ├── ffmpeg.py      # FFmpeg multimedia framework (Autotools)
    ├── uamqp.py       # azure-uamqp-c (CMake)
    ├── opendds.py     # OpenDDS (MPC/ACE-TAO)
    ├── aom.py         # libaom AV1 codec (CMake)
    ├── cmake.py       # Generic CMake projects
    └── rust.py        # Cargo/Rust projects
```

## Supported Build Systems

| Build System | Feature Flag Format | Example |
|---|---|---|
| Make | `WITH_FEATURE=yes/no` | `WITH_TLS=yes` |
| CMake | `-DCONFIG_FEATURE=1/0` | `-DCONFIG_TLS=1` |
| Autotools | `--enable/--disable-feature` | `--disable-decoder=dca` |
| Cargo | `--features feature` | `--features qlog` |

Feature discovery runs **every** analyzer whose build system is present and merges the results,
because a project can expose different features through different build systems — Mosquitto ships
both `CMakeLists.txt` and `config.mk`, and declares BRIDGE, PERSISTENCE, WEBSOCKETS, SYS_TREE and
MEMORY_TRACKING only in the latter.

## Output

PRAT generates:
- Coverage directories: `coverage_files_WITH_{FEATURE}_{yes|no}/`, plus `coverage_files_all_features/`
  for a batch run's baseline
- `report.html` — removable lines per source file
- `FDG.dot` — the feature graph as Graphviz (feature → file → line-range)
- `feature_graph.html` — interactive three-tier graph (feature → files → line sets); a
  single-feature run yields a one-root graph, a batch run the whole DAG. Self-contained: D3
  is vendored and inlined, so the page opens offline
- `comparison_reports/` — the paper's side-by-side reports: per-line execution state in both
  builds with `D_f` marked, and original-vs-debloated source after a removal
- `report.json` and `workflow_checkpoint.json` — machine-readable results

## Docker Demos

Eight demos cover all seven paper evaluation codebases (Mosquitto has two). Each clones and
verifies an exact target commit, maps one feature, removes the exact mapped lines, rebuilds, replays the
tests, and records the source commit, tool versions, execution evidence, and run identity.

Expected values come from `paper_expected_results.json`, where every figure is traceable to
`paper/results/code_removal.csv` (the paper's per-feature data) or to Table 4 (whole-program
totals). **Four demos analyze a feature the paper publishes no line count for**; those are
measured and reported as `OBSERVED` rather than scored, because there is nothing published to
compare them against. See [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the methodology and for
why each substitution was necessary.

| Demo | Project / version | Feature analyzed | Build | Paper value |
|---|---|---|---|---|
| `mosquitto-tls` | Mosquitto v2.0.15 | `TLS` | make | **790** LOC |
| `mosquitto-bridge` | Mosquitto v2.0.15 | `Bridge` | make | **640** LOC |
| `uamqp-websockets` | azure-uamqp-c v1.2.0 | `use_wsio` | cmake | **26** LOC |
| `opendds-content-filtered-topic` | OpenDDS DDS-3.25 | `content-filtered-topic` | MPC | **73** LOC |
| `ffmpeg-dca` | FFmpeg n5.1.4 | `decoder=dca` | autotools | none published |
| `quiche-qlog` | quiche 0.20.1 | `qlog` | cargo | none published |
| `rav1e-serialize` | rav1e v0.7.1 | `serialize` | cargo | none published |
| `aom-encoder` | libaom v3.7.1 | `CONFIG_AV1_ENCODER` | cmake | none published |

> **No results are committed.** The mapping algorithm was corrected after the last snapshot was
> taken, so every number must be regenerated on the reviewer's machine. See
> [`results/README.md`](results/README.md) and [`ARTIFACT.md`](ARTIFACT.md).

```bash
# Disk-safe compatibility corpus: map → remove → verify each source-pinned target
make compatibility-check

# Or one demo at a time, removing its (large) image afterward:
python3 src/demo-runner.py --build mosquitto-tls
python3 src/demo-runner.py --run mosquitto-tls --cleanup --output results/docker

# Compare one completed target with the corresponding published number:
python3 scripts/validate_paper_results.py results/docker/ \
  --target mosquitto-tls --strict
```

> **Disk note:** the C/C++ targets (ffmpeg, aom, opendds) produce multi-GB images. Always run
> with `--cleanup` (or `make compatibility-check`, which removes each image after its run) so the
> Docker VM disk is not exhausted.

See `docker/README.md` for detailed Docker instructions and `REPRODUCIBILITY.md` for results.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/prat/

# Lint
ruff check src/
```

## Documentation

- [Artifact guide](ARTIFACT.md) — for reviewers: what to run first, how long it takes, what success looks like
- [Reproducibility report](REPRODUCIBILITY.md) — methodology, provenance of every paper number, and limitations
- [Paper Alignment](docs/PAPER_ALIGNMENT.md) — each paper claim mapped to the code and the tests that pin it
- [API Reference](docs/API.md)
- [Usage Examples](docs/EXAMPLES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Docker Demos](docker/README.md)

## Citation

If you use PRAT or build on this work, please cite the paper:

```bibtex
@article{williams2021guided,
  author    = {Williams, Ryan and Ren, Tongwei and De Carli, Lorenzo and Lu, Long and Smith, Gillian},
  title     = {Guided Feature Identification and Removal for Resource-constrained Firmware},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  volume    = {31},
  number    = {2},
  pages     = {1--25},
  year      = {2021},
  publisher = {Association for Computing Machinery},
  address   = {New York, NY, USA},
  issn      = {1049-331X},
  doi       = {10.1145/3487568},
  url       = {https://doi.org/10.1145/3487568}
}
```

> Ryan Williams, Tongwei Ren, Lorenzo De Carli, Long Lu, and Gillian Smith. 2021.
> *Guided Feature Identification and Removal for Resource-constrained Firmware.*
> ACM Transactions on Software Engineering and Methodology 31, 2: 1–25.
> https://doi.org/10.1145/3487568

A machine-readable [`CITATION.cff`](CITATION.cff) is also provided (GitHub renders a
"Cite this repository" button from it).

## Authors

- **Ryan Williams** — author and maintainer
- Tongwei Ren, Lorenzo De Carli, Long Lu, Gillian Smith — paper co-authors

## Versioning & releases

PRAT follows [Semantic Versioning](https://semver.org/). The current version is declared in
[`pyproject.toml`](pyproject.toml); release history is in [`CHANGELOG.md`](CHANGELOG.md).

## License

PRAT is released under the [MIT License](LICENSE).
