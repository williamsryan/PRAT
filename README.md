# PRAT — Protocol Representation and Analysis Toolkit

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

Three reproducible demos with pinned dependencies:

| Demo | Project | Feature | Expected Lines | Time |
|---|---|---|---|---|
| mosquitto-tls | Mosquitto | TLS | 500–1500 | 2–5 min |
| mosquitto-bridge | Mosquitto | Bridge | 300–800 | 2–5 min |
| ffmpeg-x264 | FFmpeg | x264 | 1000–5000 | 10–20 min |

See `docker/README.md` for detailed Docker instructions.

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
- [Usage Examples](docs/EXAMPLES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Docker Demos](docker/README.md)

## License

See `LICENSE.txt` for license information.
