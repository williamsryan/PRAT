# PRAT API Documentation

## Overview

PRAT provides a modular Python API for analyzing feature-specific code in C/C++/Rust projects. This document describes the public interfaces for each module.

## Core Modules

### workflow.py

Main orchestration module for running complete PRAT analysis.

#### `run_complete_workflow()`

Execute the complete PRAT analysis workflow.

```python
def run_complete_workflow(
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: Optional[str] = None,
    build_system: Optional[BuildSystem] = None,
    adapter: Optional[ProjectAdapter] = None,
    symbolic: bool = False,
    klee_config: Optional[KleeConfig] = None,
) -> WorkflowResult
```

**Parameters:**
- `project_path`: Path to project root directory
- `feature`: Feature name to analyze (e.g., "TLS", "BRIDGE")
- `run_tests`: Whether to run test suite after compilation
- `output_dir`: Directory for output files (defaults to project_path)
- `build_system`: Build system to use (auto-detected if None)
- `adapter`: ProjectAdapter to use (auto-detected if None); overrides build_system
- `symbolic`: Generate KLEE symbolic tests (experimental; requires KLEE)
- `klee_config`: KLEE configuration

**Returns:** `WorkflowResult` with all outputs and statistics

**Example:**
```python
from prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS"
)

if result.success:
    print(f"Found {result.extraction_result.total_removable_lines} removable lines")
```

#### `resume_workflow()`

Resume workflow from a checkpoint after error.

> **Note:** Resume logic is not yet fully implemented. The function currently re-runs the complete workflow from the beginning regardless of the checkpoint. The checkpoint file still records which step failed, which is useful for debugging.

```python
def resume_workflow(
    checkpoint_file: str,
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: Optional[str] = None
) -> WorkflowResult
```

### compilation.py

Module for compiling projects with feature flags.

#### `compile_project()`

Compile project with specified feature flag (generic, build-system-dispatch path).

```python
def compile_project(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool = False,
    build_system: Optional[BuildSystem] = None
) -> CompilationResult
```

#### `compile_with_adapter()`

Compile using a ProjectAdapter (preferred path when an adapter is available).

```python
def compile_with_adapter(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
    run_tests: bool = False
) -> CompilationResult
```

#### `detect_build_system()`

Detect project build system from project files.

```python
def detect_build_system(project_path: str) -> BuildSystem
```

**Returns:** `BuildSystem` enum value (MAKE, CMAKE, AUTOTOOLS, CARGO, UNKNOWN)

### coverage.py

Module for generating coverage files.

#### `generate_coverage()`

Run gcov/llvm-cov on compiled source files.

```python
def generate_coverage(
    project_path: str,
    feature: str,
    enabled: bool,
    build_system: BuildSystem,
    coverage_tool: str = "auto"
) -> CoverageResult
```

#### `generate_coverage_with_adapter()`

Generate coverage using a ProjectAdapter (preferred path).

```python
def generate_coverage_with_adapter(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
) -> CoverageResult
```

#### `execute_for_coverage()`

Execute the compiled binary/test suite to generate `.gcda` profile data (dynamic coverage).

```python
def execute_for_coverage(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
    timeout: int = 300,
) -> bool
```

### diff.py

Module for comparing coverage files.

#### `diff_coverage_files()`

Generate unified diffs between matching coverage files.

```python
def diff_coverage_files(
    enabled_dir: str,
    disabled_dir: str,
    feature: str,
    output_dir: Optional[str] = None
) -> DiffResult
```

**Returns:** `DiffResult` with paths to diff files and statistics

### extraction.py

Module for extracting feature-specific code from diffs.

#### `extract_features()`

Parse diff files and extract feature-specific code.

```python
def extract_features(
    diff_dir: str,
    feature: str = "",
    output_dir: Optional[str] = None
) -> ExtractionResult
```

**Returns:** `ExtractionResult` with line counts and file mappings

### discovery.py

Module for discovering available features in projects.

All discovery functions return `List[Feature]` (not `List[str]`).

#### `discover_features()`

Auto-detect build system and discover features.

```python
def discover_features(project_path: str) -> List[Feature]
```

#### `discover_features_make()`

```python
def discover_features_make(project_path: str) -> List[Feature]
```

#### `discover_features_cmake()`

```python
def discover_features_cmake(project_path: str) -> List[Feature]
```

#### `discover_features_autotools()`

```python
def discover_features_autotools(project_path: str) -> List[Feature]
```

#### `discover_features_cargo()`

```python
def discover_features_cargo(project_path: str) -> List[Feature]
```

### docker_runner.py

Module for Docker container orchestration.

#### `build_docker_image()`

```python
def build_docker_image(
    dockerfile_path: str,
    image_name: str,
    build_context: Optional[str] = None,
    build_args: Optional[Dict[str, str]] = None,
    no_cache: bool = False
) -> bool
```

#### `run_docker_container()`

```python
def run_docker_container(
    image_name: str,
    container_name: Optional[str] = None,
    volumes: Optional[Dict[str, str]] = None,
    environment: Optional[Dict[str, str]] = None,
    command: Optional[List[str]] = None,
    remove: bool = True,
    detach: bool = False,
    timeout: Optional[int] = None
) -> ContainerResult
```

## Data Models

### WorkflowResult

```python
@dataclass
class WorkflowResult:
    success: bool
    project: str
    feature: str
    compilation_enabled: Optional[CompilationResult]
    compilation_disabled: Optional[CompilationResult]
    coverage_enabled: Optional[CoverageResult]
    coverage_disabled: Optional[CoverageResult]
    diff_result: Optional[DiffResult]
    extraction_result: Optional[ExtractionResult]
    total_time: float
    checkpoint: WorkflowCheckpoint
    error_message: Optional[str] = None
```

### CompilationResult

```python
@dataclass
class CompilationResult:
    success: bool
    binary_path: Optional[str]
    error_message: Optional[str]
    compilation_time: float
    coverage_enabled: bool
    build_system: BuildSystem
```

### CoverageResult

```python
@dataclass
class CoverageResult:
    success: bool
    coverage_files: List[str]
    coverage_dir: str
    missing_files: List[str]
    error_message: Optional[str]
```

### DiffResult

```python
@dataclass
class DiffResult:
    success: bool
    diff_dir: str
    diff_files: List[str]
    feature_only_files: List[str]
    total_diffs: int
    error_message: Optional[str]
```

### ExtractionResult

```python
@dataclass
class ExtractionResult:
    success: bool
    file_line_counts: Dict[str, int]       # filename -> removable line count
    total_removable_lines: int
    file_line_numbers: Dict[str, List[int]] # filename -> list of line numbers
    file_line_content: Dict[str, List[str]] # filename -> list of source snippets
    html_report_path: Optional[str]
    dot_graph_path: Optional[str]
    error_message: Optional[str]
```

### Feature

```python
@dataclass
class Feature:
    name: str
    description: Optional[str] = None
    default_enabled: Optional[bool] = None
```

### ContainerResult

```python
@dataclass
class ContainerResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    container_id: Optional[str] = None
    error_message: Optional[str] = None
```

## Usage Examples

### Example 1: Analyze Mosquitto TLS

```python
from prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS",
    run_tests=False
)

if result.success:
    print(f"Analysis complete!")
    print(f"Removable lines: {result.extraction_result.total_removable_lines}")
    print(f"Files analyzed: {len(result.extraction_result.file_line_counts)}")
    print(f"HTML report: {result.extraction_result.html_report_path}")
```

### Example 2: Discover Features

```python
from prat.discovery import discover_features_make

features = discover_features_make("App/mosquitto")
for f in features:
    print(f"{f.name}: {f.description}")
```

### Example 3: Build and Run Docker Demo

```python
from prat.docker_runner import build_docker_image, run_docker_container

success = build_docker_image(
    dockerfile_path="docker/demo1/Dockerfile",
    image_name="prat-demo:mosquitto-tls",
    build_context="."
)

if success:
    result = run_docker_container(
        image_name="prat-demo:mosquitto-tls",
        volumes={"./output": "/prat/output"},
        remove=True
    )
    print(f"Container exit code: {result.exit_code}")
```

### Example 4: Custom Build System

```python
from prat.compilation import BuildSystem, compile_project

result = compile_project(
    project_path="my-project",
    feature="MY_FEATURE",
    enabled=True,
    build_system=BuildSystem.CMAKE
)

if result.success:
    print(f"Compilation successful: {result.binary_path}")
```

### Example 5: Custom Project Adapter

```python
from prat.adapters.base import ProjectAdapter
from prat.compilation import BuildSystem
from typing import List, Optional

class MyProjectAdapter(ProjectAdapter):
    @property
    def build_system(self) -> BuildSystem:
        return BuildSystem.MAKE

    @property
    def coverage_tool(self) -> str:
        return "gcov"

    @property
    def source_directories(self) -> List[str]:
        return ["src"]

    def get_compile_command(
        self, feature: str, enabled: bool, with_coverage: bool = True
    ) -> List[str]:
        flag = "yes" if enabled else "no"
        cmd = ["make", f"WITH_{feature.upper()}={flag}"]
        if with_coverage:
            cmd.append("WITH_COVERAGE=yes")
        return cmd

    def get_clean_command(self) -> List[str]:
        return ["make", "clean"]

    def get_test_command(self) -> Optional[List[str]]:
        return ["make", "test"]

    def format_feature_flag(self, feature: str, enabled: bool) -> str:
        return f"WITH_{feature.upper()}={'yes' if enabled else 'no'}"
```

## Error Handling

All functions return result objects with:
- `success`: Boolean indicating success/failure
- `error_message`: Optional error description

Check the `success` field before accessing other result fields:

```python
result = run_complete_workflow(...)

if not result.success:
    print(f"Workflow failed: {result.error_message}")
    print(f"Failed at checkpoint: {result.checkpoint.value}")
else:
    # Process successful results
    pass
```

## Checkpoints

PRAT saves a `workflow_checkpoint.json` after each step. The checkpoint records which step was last completed and is useful for debugging failures:

```python
from prat.workflow import resume_workflow

# Note: currently re-runs from the beginning, but checkpoint file
# contains the failure context for inspection.
result = resume_workflow(
    checkpoint_file="App/mosquitto/workflow_checkpoint.json",
    project_path="App/mosquitto",
    feature="TLS"
)
```

## See Also

- [Troubleshooting Guide](TROUBLESHOOTING.md)
- [Docker Demo Guide](../docker/README.md)
- [Contributing Guidelines](../CONTRIBUTING.md)
