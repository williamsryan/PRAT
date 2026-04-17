# PRAT - Protocol Representation and Analysis Toolkit

![](https://github.com/RiS3-Lab/PRAT/workflows/Demo-Container-Build/badge.svg)

PRAT is a research tool for identifying and removing feature-specific code from C/C++ projects using compile-time coverage analysis. It compiles a project with and without a feature flag, generates coverage data, and identifies code that can be safely removed.

## Quick Start

### Prerequisites

- Python 3.8+
- Docker (for reproducible demos)
- Build tools: gcc, make, cmake
- Coverage tools: gcov or llvm-cov

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd PRAT
```

2. Install Python dependencies:
```bash
pip3 install -r requirements.txt
```

3. Verify dependencies:
```bash
python3 -c "from src.prat.environment import verify_dependencies; print(verify_dependencies())"
```

### Running PRAT

#### Using the Workflow API (Recommended)

```python
from src.prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS",
    run_tests=False
)

print(f"Removable lines: {result.extraction_result.total_removable_lines}")
```

#### Using Docker Demos

Build and run a demo:
```bash
# Build demo
python3 src/demo-runner.py --build mosquitto-tls

# Run demo
python3 src/demo-runner.py --run mosquitto-tls --output demo_output

# Run all demos
python3 src/demo-runner.py --run-all --output demo_output
```

#### Using Legacy CLI

From the `src` directory:
```bash
python3 PRAT.py <project-path> <feature> [--extract] [--tests]
```

Options:
- `--list`: List available features for the project
- `--extract`: Generate HTML report and DOT graph
- `--tests`: Run test suite during compilation
- `--delete`: Remove feature-specific files (experimental)

## Architecture

PRAT uses a modular architecture with the following components:

- **environment.py**: Dependency verification and setup
- **compilation.py**: Project compilation with feature flags
- **coverage.py**: Coverage file generation using gcov/llvm-cov
- **diff.py**: Coverage file comparison and diff generation
- **extraction.py**: Feature-specific code identification
- **reporting.py**: HTML and DOT graph generation
- **workflow.py**: End-to-end workflow orchestration
- **discovery.py**: Automatic feature discovery
- **docker_runner.py**: Docker container orchestration
- **adapters/**: Project-specific build system adapters

## Supported Projects

PRAT supports multiple build systems:

- **Make**: Direct make commands (e.g., Mosquitto)
- **Autotools**: configure scripts (e.g., FFmpeg)
- **CMake**: CMake-based projects
- **Cargo**: Rust projects

## How It Works

1. **Compile with feature enabled**: Build project with feature flag ON
2. **Generate coverage (enabled)**: Run gcov/llvm-cov to get coverage files
3. **Compile with feature disabled**: Build project with feature flag OFF
4. **Generate coverage (disabled)**: Run gcov/llvm-cov again
5. **Diff coverage files**: Compare coverage to identify differences
6. **Extract features**: Parse diffs for lines marked `#####` (never executed)
7. **Generate reports**: Create HTML table and DOT graph visualization

## Output

PRAT generates:
- Coverage files in `coverage_files_WITH_FEATURE_{yes|no}/`
- Diff files in `diff_FEATURE/`
- HTML report showing removable lines per file
- DOT graph showing file relationships
- Workflow checkpoint for resume capability

## Examples

### Analyze Mosquitto TLS Feature

```python
from src.prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS"
)
```

### Analyze FFmpeg x264 Encoder

```python
from src.prat.workflow import run_complete_workflow
from src.prat.compilation import BuildSystem

result = run_complete_workflow(
    project_path="App/FFmpeg",
    feature="x264",
    build_system=BuildSystem.AUTOTOOLS
)
```

### Discover Available Features

```python
from src.prat.discovery import discover_features_make

features = discover_features_make("App/mosquitto")
print(f"Available features: {features}")
```

## Troubleshooting

### Missing Dependencies

If you see "Missing dependencies" errors:
```bash
# Install build tools
sudo apt-get install gcc make cmake

# Install coverage tools
sudo apt-get install gcov llvm-9

# Install Python packages
pip3 install toml pandas
```

### Compilation Failures

If compilation fails:
- Check that the project builds normally without PRAT
- Verify feature flag syntax matches the project's build system
- Check build logs in the project directory

### No Coverage Files Generated

If coverage files are missing:
- Ensure compilation used coverage flags (`-fprofile-arcs -ftest-coverage`)
- Check that gcov/llvm-cov is in your PATH
- Verify .gcno files were created during compilation

### Empty Diff Files

If all diffs are empty:
- The feature may not affect code execution paths
- Try running with `--tests` flag to execute test suites
- Verify the feature flag actually changes compilation

## Docker Demos

See `docker/README.md` for detailed Docker demo documentation.

## API Documentation

See individual module docstrings for detailed API documentation:
- `src/prat/workflow.py`: Workflow orchestration
- `src/prat/compilation.py`: Compilation interface
- `src/prat/coverage.py`: Coverage generation
- `src/prat/diff.py`: Coverage diffing
- `src/prat/extraction.py`: Feature extraction
- `src/prat/docker_runner.py`: Docker orchestration

## Contributing

See `CONTRIBUTING.md` for contribution guidelines.

## License

See `LICENSE.txt` for license information.
