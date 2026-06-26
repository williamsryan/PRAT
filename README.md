# PRAT — Protocol Representation and Analysis Toolkit

[![CI](https://github.com/RiS3-Lab/PRAT/actions/workflows/ci.yml/badge.svg)](https://github.com/RiS3-Lab/PRAT/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-168%20passing-brightgreen.svg)](src/tests)
[![Reproducibility](https://img.shields.io/badge/reproducibility-documented-informational.svg)](REPRODUCIBILITY.md)


PRAT identifies and extracts feature-specific code from C/C++/Rust projects using **compile-time differential coverage analysis**. It compiles a project with and without a feature flag, generates coverage data, and identifies code that can be safely removed.

## How It Works

1. **Compile with feature enabled** → instrument with coverage flags
2. **Generate coverage** (enabled) → gcov/llvm-cov produces `.gcov` files
3. **Compile with feature disabled** → same instrumentation
4. **Generate coverage** (disabled) → second set of `.gcov` files
5. **Diff coverage files** → identify lines unique to the feature-enabled build
6. **Extract feature code** → lines marked `#####` (never executed when feature is off)
7. **Generate reports** → HTML table + DOT graph of removable code

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
```

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
├── compilation.py     # Multi-build-system compilation (Make, CMake, Autotools, Cargo)
├── coverage.py        # gcov/llvm-cov coverage generation
├── diff.py            # Coverage file comparison
├── extraction.py      # Feature-specific line identification
├── reporting.py       # HTML report + DOT graph generation
├── discovery.py       # Automatic feature flag discovery
├── docker_runner.py   # Docker container orchestration
└── adapters/          # Project-specific build adapters
    ├── base.py        # Abstract adapter interface
    ├── mosquitto.py   # Mosquitto MQTT broker
    ├── ffmpeg.py      # FFmpeg multimedia framework
    ├── cmake.py       # Generic CMake projects
    └── rust.py        # Cargo/Rust projects
```

## Supported Build Systems

| Build System | Feature Flag Format | Example |
|---|---|---|
| Make | `WITH_FEATURE=yes/no` | `WITH_TLS=yes` |
| CMake | `-DCONFIG_FEATURE=1/0` | `-DCONFIG_TLS=1` |
| Autotools | `--enable/--disable-feature` | `--disable-x264` |
| Cargo | `--features feature` | `--features tls` |

## Output

PRAT generates:
- Coverage directories: `coverage_files_WITH_{FEATURE}_{yes|no}/`
- Diff directory: `diff_{FEATURE}/`
- HTML report showing removable lines per source file
- DOT graph showing file/feature relationships
- JSON checkpoint file for workflow resume

## Docker Demos

Seven reproducible demos cover the paper's Table 4 evaluation targets. Each demo is
self-contained (clones the target at a pinned tag, builds it with the feature on/off, runs
gcov, diffs, extracts) and writes a `manifest.json` recording the exact git commit and tool
versions used.

PRAT reports **two metrics**: `interleaved` (feature code inside files shared by both builds)
and a paper-aligned `combined` value that also counts dedicated feature-only files. See
[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the full methodology, per-target results, and an
honest account of where the static analysis diverges from the paper's KLEE-based numbers.

| Demo | Project / version | Feature | Build | Accept. range | Status (this env) |
|---|---|---|---|---|---|
| mosquitto-tls | Mosquitto v2.0.15 | TLS | make | 500–1800 | ✅ reproduces (1415) |
| mosquitto-bridge | Mosquitto v2.0.15 | BRIDGE | make | 300–900 | ✅ reproduces (545) |
| uamqp-websockets | azure-uamqp-c v1.2.0 | use_wsio | cmake | 200–2000 | 🟢 reproduces, paper-aligned metric (1282) |
| aom-encoder | libaom v3.7.1 | CONFIG_AV1_ENCODER | cmake | 5000–50000 | ✅ reproduces via dynamic coverage (8691) |
| ffmpeg-x264 | FFmpeg n5.1.4 | x264 → decoder=dca | autotools | 1000–5000 | 🟢 substitute feature (DTS decoder) — x264 is external-lib; 3728 |
| opendds-security | OpenDDS DDS-3.25 | SECURITY | MPC/ACE-TAO | 500–5000 | ⚠️ builds & runs; static diff over-counts generated code (49677) |
| quiche-ffdhe | quiche 0.20.1 | ffdhe → qlog | cargo | 100–1500 | 🟢 substitute feature (qlog) — ffdhe absent (drift); 420 |

```bash
# Disk-safe full pipeline: per-demo build → run → remove image, then validate
make paper-check

# Or one demo at a time, removing its (large) image afterward:
python3 src/demo-runner.py --build mosquitto-tls
python3 src/demo-runner.py --run mosquitto-tls --cleanup --output results/docker

# Validate whatever has run against the paper numbers:
python3 scripts/validate_paper_results.py results/docker/ --json results/validation_report.json
```

> **Disk note:** the C/C++ targets (ffmpeg, aom, opendds) produce multi-GB images. Always run
> with `--cleanup` (or `make paper-check`, which removes each image right after its run) so the
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

- [API Reference](docs/API.md)
- [Paper Alignment](docs/PAPER_ALIGNMENT.md)
- [Usage Examples](docs/EXAMPLES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Docker Demos](docker/README.md)

## License

See `LICENSE.txt` for license information.
