# PRAT API Documentation

## Overview

PRAT provides a modular Python API for analyzing feature-specific code in C/C++ projects. This document describes the public interfaces for each module.

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
    build_system: Optional[BuildSystem] = None
) -> WorkflowResult
```

**Parameters:**
- `project_path`: Path to project root directory
- `feature`: Feature name to analyze (e.g., "TLS", "BRIDGE")
- `run_tests`: Whether to run test suite after compilation
- `output_dir`: Directory for output files (defaults to project_path)
- `build_system`: Build system to use (auto-detected if None)

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

```python
def resume_workflow(
    checkpoint_file: str,
    project_path: str,
    feature: str,
    run_tests: bool = False,
    output_dir: Optional[str] = None
) -> WorkflowResult
```

**Parameters:**
- `checkpoint_file`: Path to checkpoint JSON file
- `project_path`: Path to project root directory
- `feature`: Feature name to analyze
- `run_tests`: Whether to run test suite
- `output_dir`: Directory for output files

**Returns:** `WorkflowResult` from resumed execution

### compilation.py

Module for compiling projects with feature flags.

#### `compile_project()`

Compile project with specified feature flag.

```python
def compile_project(
    project_path: str,
    feature: str,
    enabled: bool,
    run_tests: bool = False,
    build_system: Optional[BuildSystem] = None
) -> CompilationResult
```

**Parameters:**
- `project_path`: Path to project root
- `feature`: Feature name (e.g., "TLS")
- `enabled`: True for feature enabled, False for disabled
- `run_tests`: Whether to run test suite after compilation
- `build_system`: Build system to use (auto-detected if None)

**Returns:** `CompilationResult` with status and error messages

#### `detect_build_system()`

Detect project build system.

```python
def detect_build_system(project_path: str) -> BuildSystem
```

**Returns:** `BuildSystem` enum value (MAKE, CMAKE, AUTOTOOLS, CARGO)

### coverage.py

Module for generating coverage files.

#### `generate_coverage()`

Run gcov/llvm-cov on compiled source files.

```python
def generate_coverage(
    project_path: str,
    feature: str,
    enabled: bool
) -> CoverageResult
```

**Parameters:**
- `project_path`: Path to project root
- `feature`: Feature name
- `enabled`: Whether feature was enabled during compilation

**Returns:** `CoverageResult` with paths to generated .gcov files

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

**Parameters:**
- `enabled_dir`: Directory with feature-enabled coverage
- `disabled_dir`: Directory with feature-disabled coverage
- `feature`: Feature name for output directory naming
- `output_dir`: Base directory for diff output

**Returns:** `DiffResult` with paths to diff files and statistics

### extraction.py

Module for extracting feature-specific code from diffs.

#### `extract_features()`

Parse diff files and extract feature-specific code.

```python
def extract_features(
    diff_dir: str,
    feature: str,
    output_dir: Optional[str] = None
) -> ExtractionResult
```

**Parameters:**
- `diff_dir`: Directory containing diff files
- `feature`: Feature name
- `output_dir`: Directory for output reports

**Returns:** `ExtractionResult` with line counts and file mappings

### docker_runner.py

Module for Docker container orchestration.

#### `build_docker_image()`

Build Docker image from Dockerfile.

```python
def build_docker_image(
    dockerfile_path: str,
    image_name: str,
    build_context: Optional[str] = None,
    build_args: Optional[Dict[str, str]] = None,
    no_cache: bool = False
) -> bool
```

**Parameters:**
- `dockerfile_path`: Path to Dockerfile
- `image_name`: Name and tag for the image
- `build_context`: Build context directory
- `build_args`: Build arguments to pass to Docker
- `no_cache`: If True, build without cache

**Returns:** True if build successful

#### `run_docker_container()`

Run Docker container and return results.

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

**Parameters:**
- `image_name`: Name of Docker image to run
- `container_name`: Optional name for the container
- `volumes`: Dictionary mapping host paths to container paths
- `environment`: Environment variables to set
- `command`: Command to run (overrides Dockerfile CMD)
- `remove`: Auto-remove container when it exits
- `detach`: Run in background
- `timeout`: Maximum execution time in seconds

**Returns:** `ContainerResult` with output and exit code

### discovery.py

Module for discovering available features in projects.

#### `discover_features_make()`

Discover features in Make-based projects.

```python
def discover_features_make(project_path: str) -> List[str]
```

#### `discover_features_cmake()`

Discover features in CMake projects.

```python
def discover_features_cmake(project_path: str) -> List[str]
```

#### `discover_features_autotools()`

Discover features in Autotools projects.

```python
def discover_features_autotools(project_path: str) -> List[str]
```

#### `discover_features_cargo()`

Discover features in Rust/Cargo projects.

```python
def discover_features_cargo(project_path: str) -> List[str]
```

## Data Models

### WorkflowResult

Complete workflow execution result.

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

Result of project compilation.

```python
@dataclass
class CompilationResult:
    success: bool
    binary_path: Optional[str]
    error_message: Optional[str]
    compilation_time: float
    coverage_enabled: bool
```

### CoverageResult

Result of coverage generation.

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

Result of coverage diff analysis.

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

Result of feature extraction.

```python
@dataclass
class ExtractionResult:
    success: bool
    file_line_counts: Dict[str, int]
    total_removable_lines: int
    html_report_path: Optional[str]
    dot_graph_path: Optional[str]
    error_message: Optional[str]
```

### ContainerResult

Result of Docker container execution.

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
from src.prat.workflow import run_complete_workflow

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
from src.prat.discovery import discover_features_make

features = discover_features_make("App/mosquitto")
print(f"Available features: {', '.join(features)}")
```

### Example 3: Build and Run Docker Demo

```python
from src.prat.docker_runner import build_docker_image, run_docker_container

# Build image
success = build_docker_image(
    dockerfile_path="docker/demo1/Dockerfile",
    image_name="prat-demo:mosquitto-tls",
    build_context="."
)

if success:
    # Run container
    result = run_docker_container(
        image_name="prat-demo:mosquitto-tls",
        volumes={"./output": "/prat/output"},
        remove=True
    )
    
    print(f"Container exit code: {result.exit_code}")
```

### Example 4: Custom Build System

```python
from src.prat.compilation import BuildSystem, compile_project

result = compile_project(
    project_path="my-project",
    feature="MY_FEATURE",
    enabled=True,
    build_system=BuildSystem.CMAKE
)

if result.success:
    print(f"Compilation successful: {result.binary_path}")
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

## Checkpoints and Resume

PRAT saves checkpoints during workflow execution. To resume after failure:

```python
from src.prat.workflow import resume_workflow

result = resume_workflow(
    checkpoint_file="App/mosquitto/workflow_checkpoint.json",
    project_path="App/mosquitto",
    feature="TLS"
)
```

## Advanced Usage

### Custom Project Adapters

Create custom adapters for unsupported build systems:

```python
from src.prat.adapters.base import ProjectAdapter

class MyProjectAdapter(ProjectAdapter):
    def get_compile_command(self, feature: str, enabled: bool) -> List[str]:
        # Return custom compile command
        pass
    
    def get_clean_command(self) -> List[str]:
        # Return custom clean command
        pass
```

### Parallel Processing

For large projects, consider running coverage generation in parallel:

```python
from concurrent.futures import ThreadPoolExecutor
from src.prat.coverage import generate_coverage

with ThreadPoolExecutor(max_workers=4) as executor:
    # Submit coverage tasks
    futures = [
        executor.submit(generate_coverage, path, feature, enabled)
        for path, feature, enabled in tasks
    ]
    
    # Collect results
    results = [f.result() for f in futures]
```

## See Also

- [Troubleshooting Guide](TROUBLESHOOTING.md)
- [Docker Demo Guide](../docker/README.md)
- [Contributing Guidelines](CONTRIBUTING.md)