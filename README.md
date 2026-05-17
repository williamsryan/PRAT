# PRAT — Protocol Representation and Analysis Toolkit

PRAT identifies and extracts feature-specific code from C/C++/Rust projects using **differential dynamic coverage analysis**. It builds a coverage-instrumented feature-active variant and a feature-disabled variant, executes available workloads/tests, diffs coverage data, and reports lines that are observed only when the feature is active.

This repository is a modernized, research-prototype implementation of the technique from Williams et al., *Guided Feature Identification and Removal for Resource-Constrained Firmware* (ACM TOSEM 2021). The core feature discovery, build/coverage diffing, reporting, batch analysis, and source-removal paths are implemented and tested. KLEE-based symbolic test generation and post-removal verification exist, but should be treated as experimental until validated in the target Docker/KLEE environment.

## How It Works

1. **Discover features** from Make, CMake, Autotools, or Cargo build metadata
2. **Compile feature-active build** with coverage flags
3. **Execute available workloads/tests** so `.gcda` profile data is written
4. **Compile feature-disabled build** with the same instrumentation
5. **Execute the same workloads/tests** against the disabled build
6. **Diff coverage files** to identify lines covered only in the feature-active build
7. **Generate reports**: HTML, JSON, DOT, and optional feature graph
8. **Optionally remove and verify** identified lines from the source tree

## Quick Start

### Prerequisites

- Python 3.9+
- Docker (for reproducible demos)
- Build tools: gcc, make, cmake
- Coverage tools: gcov or llvm-cov

### Setup

```bash
git clone <repository-url>
cd PRAT
make setup      # create .venv and install prat + dev deps
make fetch      # clone Mosquitto v2.0.15 and FFmpeg n5.1.4 into App/
```

Or manually:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./scripts/fetch-targets.sh
```

### Run an Analysis

```bash
make demo-mosquitto-tls    # analyze Mosquitto TLS → results/mosquitto-tls/
make demo-mosquitto-bridge # analyze Mosquitto BRIDGE
make demo-ffmpeg-x264      # analyze FFmpeg x264
make demo-all              # run all three
make graph                 # open the HTML report in your browser
```

Or with the CLI directly (after `source .venv/bin/activate`):

```bash
prat App/mosquitto TLS                  # analyze a feature
prat App/mosquitto --list               # list discovered features
prat App/mosquitto TLS --dry-run        # preview without executing
prat App/mosquitto TLS --tests --verbose

# Equivalent module invocations (no install required if venv is active):
python3 -m prat App/mosquitto TLS
python3 -m prat.cli App/mosquitto TLS

# Without a venv (from repo root):
PYTHONPATH=src python3 -m prat App/mosquitto TLS
```

### Workflow API

```python
from prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS",
    run_tests=False
)

print(f"Removable lines: {result.extraction_result.total_removable_lines}")
```

### Docker Demos

Self-contained demos that clone and build the target projects inside the image:

```bash
make demo-release # stable Mosquitto TLS demo for review
make docker-build   # build all three demo images
make docker-run     # run all demos → results/docker/ + demo_report.txt
```

Or individually:

```bash
make docker-demo-mosquitto-tls
make docker-demo-ffmpeg
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
- HTML and JSON reports showing removable lines per source file
- DOT graph showing file/feature relationships
- JSON checkpoint file for workflow resume

## Docker Demos

Three reproducible demos with pinned target-project versions and stable package sets:

| Demo | Project | Feature | Expected Lines | Time |
|---|---|---|---|---|
| mosquitto-tls | Mosquitto | TLS | 500–1500 | 2–5 min |
| mosquitto-bridge | Mosquitto | Bridge | 300–800 | 2–5 min |
| ffmpeg-x264 | FFmpeg | x264 | 1000–5000 | 10–20 min |

See `docker/README.md` for detailed Docker instructions.

## Development

```bash
source .venv/bin/activate   # activate venv first

make test        # run full test suite (167 tests)
make test-fast   # stop on first failure
make lint        # ruff check src/prat/
mypy src/prat/   # type checking; currently advisory for release review

# Run a single test file or test by name
pytest src/tests/test_workflow.py
pytest -k "test_name"
```

## Documentation

- [API Reference](docs/API.md)
- [Docker Quickstart](docs/QUICKSTART_DOCKER.md)
- [Standalone Quickstart](docs/QUICKSTART_STANDALONE.md)
- [Paper Alignment](docs/PAPER_ALIGNMENT.md)
- [Release Audit](docs/RELEASE_AUDIT.md)
- [Usage Examples](docs/EXAMPLES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Docker Demos](docker/README.md)
