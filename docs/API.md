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
    output_dir: str | None = None,
    build_system: BuildSystem | None = None,
    adapter: ProjectAdapter | None = None,
    symbolic: bool = False,
    klee_config: KleeConfig | None = None,
    remove: bool = False,
    verify: bool = True,
    baseline_coverage_dir: str | None = None,
    reuse_baseline: bool = False,
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
- `remove`: Blank exactly the mapped source lines and rebuild
- `verify`: Re-run the same workload and compare it with the pre-removal output
- `baseline_coverage_dir`: Existing `L_all` directory used by batch analysis
- `reuse_baseline`: Reuse that baseline without rebuilding it

The symbolic path consumes C/C++ LLVM bitcode. A symbolic Cargo/Rust request
fails explicitly; Rust dynamic mapping uses `cargo-llvm-cov`.

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
    output_dir: str | None = None,
    symbolic_tests: list[str] | None = None,
    feature_states: dict[str, bool] | None = None,
    label: str | None = None,
    execution_commands: list[list[str]] | None = None,
    test_plan_id: str | None = None,
    allow_test_failures: bool = False,
) -> CoverageResult
```

`execution_commands` is the fixed test plan `T` (from `ProjectAdapter.get_test_plan()`), run
unchanged against every build. The recorded `test_plan_id` is recomputed from the commands that
actually ran, not taken from the caller. `allow_test_failures` is set for `B_f` builds only:
Algorithm 1 runs the same `T` against `B_f`, where the tests of `f` cannot pass; their failure
is recorded (`execution_errors`, `test_failures_tolerated`) and coverage comes from the rest of
`T`. `B_all` never tolerates a failing command.

#### `execute_for_coverage()`

Execute the compiled binary/test suite to generate `.gcda` profile data (dynamic coverage).

```python
def execute_for_coverage(
    adapter: ProjectAdapter,
    feature: str,
    enabled: bool,
    timeout: int = 300,
    symbolic_tests: list[str] | None = None,
    binary_path: str | None = None,
    execution_commands: list[list[str]] | None = None,
    allow_failures: bool = False,
) -> ExecutionResult
```

The result succeeds only when at least one unit-test command or symbolic replay
completes and, unless `allow_failures` is set, no command fails or times out.
`ExecutionResult.executed` lists the commands attempted, in order.

### gcov.py

Parses gcov output into line sets. This is the foundation of the mapping: gcov
distinguishes three states per line and only one of them counts as "executed".

#### `parse_gcov()`

```python
def parse_gcov(gcov_path: str) -> GcovFile | None
```

Returns a `GcovFile` whose `executed` set is the `L` of Algorithm 1. Lines marked
`#####` land in `never_executed` and lines marked `-` in `non_executable`;
neither is part of `L`.

#### `load_coverage_dir()`

```python
def load_coverage_dir(coverage_dir: str) -> dict[str, GcovFile]
```

Parses every gcov file in a directory, keyed by the path in each file's
`Source:` header (not the basename, which collides across directories). Files
covering the same source from different translation units are unioned.

#### `merge_contiguous()` / `format_ranges()`

```python
def merge_contiguous(line_numbers: list[int]) -> list[tuple[int, int]]
def format_ranges(line_numbers: list[int]) -> str
```

Groups line numbers into contiguous runs — the LOC-node unit of a feature graph
("contiguous lines of code are merged in a single node") — and renders them as
`"12-14, 44, 91-92"`.

### mapping.py

Implements Algorithm 1's feature-to-code mapping.

#### `map_feature()` / `map_feature_from_coverage()`

```python
def map_feature(
    feature: str,
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
) -> FeatureMapping

def map_feature_from_coverage(
    feature: str,
    enabled: dict[str, GcovFile],
    disabled: dict[str, GcovFile],
) -> FeatureMapping
```

Computes `D_f = L_all \ L_f`. Lines never executed in either build are excluded
and counted in `FeatureMapping.excluded_never_executed`, per the paper's
soundness-over-completeness design.

#### `protected_lines()`

```python
def protected_lines(mapping: FeatureMapping) -> dict[str, set[int]]
```

The `L_f` lines that must survive removal. Pass to `remove_feature_code()` so
the planner cannot absorb shared code while repairing a run.

#### `guard_context()`

```python
def guard_context(mapping: FeatureMapping) -> dict[str, GuardContext]
```

Per-file line sets the removal planner needs beyond `D_f` and `L_f`, derived
from the two coverage sets: `absorbable` (non-executable in both builds),
`unexecuted_feature_only` (compiled by `B_all` only, never executed),
`unexecuted_shared` (compiled by both, never executed) and
`executable_disabled` (everything `B_f` compiles). Pass as
`remove_feature_code(..., guard_context=...)`. With it the planner absorbs
feature-only unexecuted code, keeps guards of shared unexecuted code
(`RemovalResult.guards_shared_code`) and delimiter-only runs shared code needs
(`RemovalResult.retained_structural`) without failing `require_complete`, and
declines only runs it can neither close nor classify
(`RemovalResult.skipped_unbalanced`).

#### `coverage_percent()` / `function_percent()`

```python
def coverage_percent(coverage: dict[str, GcovFile]) -> float | None
def function_percent(coverage: dict[str, GcovFile]) -> float | None
```

Line and function coverage across a coverage set. Function data requires
`gcov -f`, which `prat.coverage` always requests.

### diff.py

Generates the paper's side-by-side code comparison reports. The authoritative
mapping lives in `mapping.py`; these reports render it for human review.

#### `generate_comparison_reports()`

```python
def generate_comparison_reports(
    mapping: FeatureMapping,
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
    output_dir: str,
    original_root: str | None = None,
    debloated_root: str | None = None,
) -> ComparisonResult
```

Writes a *coverage comparison* per file (each line's execution state in both
builds, with `D_f` marked) for auditing the mapping, and — when both a
pre-removal and post-removal tree are supplied — a *source comparison* for
auditing the removal, plus a browsable index.

### extraction.py

Packages a `FeatureMapping` for reporting and removal.

#### `extract_features()`

```python
def extract_features(
    enabled_coverage_dir: str,
    disabled_coverage_dir: str,
    feature: str = "",
    skip_generated_idl: bool = False,
) -> ExtractionResult
```

#### `extract_from_mapping()`

```python
def extract_from_mapping(
    mapping: FeatureMapping,
    skip_generated_idl: bool = False,
) -> ExtractionResult
```

**Returns:** `ExtractionResult` with line counts, line numbers, contiguous
ranges, and the partition of `D_f` over files that exist only in the
feature-enabled build. Generated IDL is included by default; skipping it is an
explicit opt-in because excluding mapped source silently would make the result
incomplete.

### discovery.py

Module for discovering available features in projects.

All discovery functions return `List[Feature]` (not `List[str]`).

#### `discover_features()`

Auto-detect build system and discover features.

```python
def discover_features(project_path: str) -> List[Feature]
```

The complete signature also accepts an adapter and filtering controls:
`discover_features(project_path, adapter=None, apply_filters=True,
keep_developer_options=False)`.

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
    extraction_result: Optional[ExtractionResult]
    total_time: float
    checkpoint: WorkflowCheckpoint
    error_message: Optional[str] = None
    symbolic_result: Optional[SymbolicResult] = None
    comparison_result: Optional[ComparisonResult] = None
    removal_result: Optional[RemovalResult] = None
    verification_result: Optional[VerificationResult] = None
    coverage_percent_enabled: Optional[float] = None
    coverage_percent_disabled: Optional[float] = None
    run_id: Optional[str] = None
    # D_f itself. Excluded from to_dict() because it carries full source text.
    mapping: Optional[FeatureMapping] = None
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
    error_message: Optional[str] = None
    dynamic_execution: bool = False
    execution_commands: int = 0
    execution_succeeded: int = 0
    execution_failed: int = 0
    execution_timed_out: int = 0
    symbolic_tests_replayed: int = 0
    test_plan_id: Optional[str] = None
    test_failures_tolerated: bool = False
    execution_errors: List[str] = field(default_factory=list)
```

`test_plan_id` is the digest of the commands this build actually executed; the workflow and
batch paths require it to match between `B_all` and every `B_f`, so the two measurements are
bound to the same `T`. `execution_errors` lists the commands of `T` that could not run against
this build (tolerated for `B_f` only). Production workflows reject coverage that lacks
successful dynamic execution.

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    commands: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    symbolic_replayed: int = 0
    symbolic_failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool: ...
```

### GcovFile

```python
@dataclass
class GcovFile:
    source_path: str              # from the gcov "Source:" header
    gcov_path: str
    executed: set[int]            # the L set of Algorithm 1
    never_executed: set[int]      # gcov "#####": executable, not run
    non_executable: set[int]      # gcov "-": no code generated
    source: dict[int, str]
    functions: dict[str, int]     # name -> call count (requires gcov -f)
```

### FeatureMapping / FileMapping

```python
@dataclass
class FeatureMapping:
    feature: str
    files: dict[str, FileMapping]     # source path -> lines in D_f
    excluded_never_executed: int      # retained, per the conservatism claim

@dataclass
class FileMapping:
    source_path: str
    lines: list[int]                  # D_f for this file
    source: dict[int, str]
    feature_only_file: bool           # present only in the enabled build
    executed_enabled: int
    executed_disabled: int
    shared_lines: set[int]            # L_f: must never be removed
    never_executed_both: list[int]
```

### ComparisonResult

```python
@dataclass
class ComparisonResult:
    success: bool
    report_dir: str
    coverage_reports: list[str]
    source_reports: list[str]
    index_path: Optional[str]
    error_message: Optional[str]
```

### ExtractionResult

```python
@dataclass
class ExtractionResult:
    success: bool
    file_line_counts: dict[str, int]        # source path -> lines in D_f
    total_removable_lines: int              # |D_f|
    file_line_numbers: dict[str, list[int]]
    file_line_content: dict[str, list[str]]
    html_report_path: Optional[str]
    dot_graph_path: Optional[str]
    error_message: Optional[str]

    # Partition of D_f over files that exist only in the enabled build. Already
    # included in total_removable_lines; tracked separately because the paper
    # contrasts dedicated feature files against interleaved code in shared files.
    feature_only_file_counts: dict[str, int]
    feature_only_removable_lines: int
    feature_only_source_paths: list[str]

    # Executable with the feature on but executed in neither build. Algorithm 1
    # leaves these in place; the count makes that trade-off visible.
    excluded_never_executed: int

    # Contiguous (start, end) runs per file — the LOC-node unit of a feature graph.
    file_line_ranges: dict[str, list[tuple[int, int]]]

    # Properties
    total_feature_lines: int           # alias of total_removable_lines
    interleaved_removable_lines: int   # D_f restricted to shared files
```

### Feature

```python
@dataclass
class Feature:
    name: str                          # adapter-facing name
    description: Optional[str] = None
    default_enabled: Optional[bool] = None
    raw_name: Optional[str] = None      # the build option, verbatim
    source: Optional[str] = None        # which analyzer found it
    filtered_reason: Optional[str] = None
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

Two more hooks matter for Algorithm 1 and are worth overriding when the defaults do not fit:

- `get_test_plan(features)` — the fixed test set `T`, run unchanged against `B_all` and every
  `B_f`. It must not depend on which feature is being analysed. The default returns
  `get_execution_commands(f, True)` for each feature in `F`, deduplicated. Override it when the
  enabled workload only works with the feature present, so that at least part of `T` runs against
  every `B_f` (the Mosquitto adapter runs a plain-listener broker session alongside its TLS one).
- `get_execution_commands(feature, enabled)` — the polarity-specific workload. The `enabled=True`
  form feeds the default `get_test_plan()`; the `enabled=False` form is not used for mapping.

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
