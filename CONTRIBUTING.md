# Contributing to PRAT

## Quick Setup

```bash
git clone <repository-url>
cd PRAT
pip install -e ".[dev]"
./scripts/fetch-targets.sh    # downloads Mosquitto + FFmpeg
pytest -v                      # run all tests
```

## Architecture

PRAT is a modular Python package. Each step of the analysis pipeline is a separate module:

```
src/prat/
├── cli.py              # Command-line interface (entry point: prat)
├── workflow.py          # End-to-end orchestration with checkpoints
├── compilation.py       # Multi-build-system compilation
├── coverage.py          # Dynamic coverage generation (gcov/llvm-cov)
├── diff.py              # Coverage file comparison
├── extraction.py        # Feature-specific line identification
├── removal.py           # Source code removal with backup/restore
├── reporting.py         # HTML, DOT, JSON report generation
├── discovery.py         # Feature auto-discovery from build configs
├── feature_graph.py     # Interactive feature graph visualization
├── symbolic.py          # KLEE symbolic test generation
├── verification.py      # Post-removal correctness testing
├── batch.py             # Multi-feature batch analysis
├── docker_runner.py     # Docker container orchestration
├── environment.py       # Dependency verification
└── adapters/            # Project-specific build adapters
    ├── base.py          # Abstract adapter interface
    ├── mosquitto.py     # Mosquitto MQTT broker
    ├── ffmpeg.py        # FFmpeg multimedia framework
    ├── cmake.py         # Generic CMake projects
    └── rust.py          # Cargo/Rust projects
```

### Key Design Patterns

- **Dataclass results**: Every module returns a typed dataclass (`CompilationResult`, `CoverageResult`, etc.)
- **Adapter pattern**: Project-specific adapters encapsulate build commands, flags, and paths
- **Adapter factory**: `get_adapter(project_path)` auto-detects the right adapter
- **Fallback pipeline**: If no adapter matches, the generic build-system dispatch is used
- **Checkpoint/resume**: Workflow saves state at each step for error recovery

### Data Flow

```
discover_features() → build configs → Feature list
     ↓
compile_with_adapter() → feature ON/OFF → binary with .gcno
     ↓
execute_for_coverage() → run tests → .gcda profile data
     ↓
generate_coverage() → gcov/llvm-cov → .gcov files
     ↓
diff_coverage_files() → unified diffs → diff files
     ↓
extract_features() → ##### markers → ExtractionResult
     ↓
generate_html_report() / generate_feature_graph_html() → reports
     ↓ (optional)
remove_feature_code() → modified source tree
     ↓ (optional)
verify_correctness() → rebuild + test replay
```

## Adding a New Project Adapter

1. Create `src/prat/adapters/myproject.py`:

```python
from .base import ProjectAdapter
from ..compilation import BuildSystem

class MyProjectAdapter(ProjectAdapter):
    @property
    def build_system(self): return BuildSystem.MAKE
    
    @property
    def coverage_tool(self): return "gcov"
    
    @property
    def source_directories(self): return ["src"]
    
    def get_compile_command(self, feature, enabled, with_coverage=True):
        flag = "yes" if enabled else "no"
        return ["make", f"FEATURE_{feature}={flag}"]
    
    def get_clean_command(self): return ["make", "clean"]
    def get_test_command(self): return ["make", "test"]
    
    def format_feature_flag(self, feature, enabled):
        return f"FEATURE_{feature}={'yes' if enabled else 'no'}"
    
    def validate_project(self):
        return (self.project_path / "my_marker_file").exists()
```

2. Register in `adapters/__init__.py`:
```python
from .myproject import MyProjectAdapter
# Add to get_adapter() adapter_classes list
```

3. Write tests in `tests/test_adapters.py`

## Running Tests

```bash
pytest -v                   # all tests
pytest tests/test_diff.py   # single file
pytest -k "test_batch"      # by pattern
```

## Code Quality

```bash
ruff check src/             # lint
```

## CLI Reference

```bash
prat App/mosquitto TLS                   # analyze single feature
prat App/mosquitto --list                # discover features
prat App/mosquitto TLS --tests           # with test suite
prat App/mosquitto TLS --dry-run         # preview only
prat App/mosquitto --batch               # all features
prat App/mosquitto TLS --remove          # analyze + remove code
prat App/mosquitto TLS --remove --verify # remove + test
prat App/mosquitto TLS --symbolic        # with KLEE tests
```
