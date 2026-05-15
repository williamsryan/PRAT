# PRAT Usage Examples

This document provides detailed examples for using PRAT with different project types and build systems.

## Example 1: Mosquitto TLS Feature (Make-based)

Mosquitto is an MQTT broker that uses Make for building. The TLS feature adds SSL/TLS encryption support.

### Using Workflow API

```python
from prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS",
    run_tests=False
)

if result.success:
    print(f"✓ Analysis complete")
    print(f"  Removable lines: {result.extraction_result.total_removable_lines}")
    print(f"  Files analyzed: {len(result.extraction_result.file_line_counts)}")
    print(f"  Execution time: {result.total_time:.2f}s")
    
    # Show top files with removable code
    sorted_files = sorted(
        result.extraction_result.file_line_counts.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    print("\n  Top files:")
    for filename, lines in sorted_files[:5]:
        print(f"    {filename}: {lines} lines")
else:
    print(f"✗ Analysis failed: {result.error_message}")
```

### Using Docker

```bash
# Build demo
python3 src/demo-runner.py --build mosquitto-tls

# Run demo
python3 src/demo-runner.py --run mosquitto-tls --output results

# Check results
cat results/mosquitto-tls/workflow_checkpoint.json
```

### Expected Results

- Removable lines: 500-1500
- Key files: `net.c`, `tls_mosq.c`
- Execution time: 2-5 minutes

## Example 2: Mosquitto Bridge Feature (Make-based)

The Bridge feature enables MQTT broker bridging for connecting multiple brokers.

### Using Workflow API

```python
from prat.workflow import run_complete_workflow

result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="BRIDGE",
    run_tests=True  # Run tests for better coverage
)

if result.success:
    extraction = result.extraction_result
    
    # Generate summary
    print(f"Bridge Feature Analysis:")
    print(f"  Total removable lines: {extraction.total_removable_lines}")
    print(f"  HTML report: {extraction.html_report_path}")
    print(f"  DOT graph: {extraction.dot_graph_path}")
    
    # Check for bridge-specific files
    bridge_files = [
        f for f in extraction.file_line_counts.keys()
        if 'bridge' in f.lower()
    ]
    
    print(f"\n  Bridge-specific files: {len(bridge_files)}")
    for f in bridge_files:
        print(f"    {f}: {extraction.file_line_counts[f]} lines")
```

### Expected Results

- Removable lines: 300-800
- Key files: `bridge.c`
- Execution time: 2-5 minutes

## Example 3: FFmpeg x264 Encoder (Autotools-based)

FFmpeg uses Autotools (configure scripts) for building. The x264 feature adds H.264 video encoding support.

### Using Workflow API

```python
from prat.workflow import run_complete_workflow
from prat.compilation import BuildSystem

result = run_complete_workflow(
    project_path="App/FFmpeg",
    feature="x264",
    build_system=BuildSystem.AUTOTOOLS
)

if result.success:
    extraction = result.extraction_result
    
    print(f"FFmpeg x264 Analysis:")
    print(f"  Removable lines: {extraction.total_removable_lines}")
    print(f"  Files analyzed: {len(extraction.file_line_counts)}")
    
    # Find libavcodec files
    codec_files = [
        f for f in extraction.file_line_counts.keys()
        if 'libavcodec' in f
    ]
    
    print(f"\n  Codec files affected: {len(codec_files)}")
```

### Using Docker

```bash
# Build demo
python3 src/demo-runner.py --build ffmpeg-x264

# Run demo
python3 src/demo-runner.py --run ffmpeg-x264 --output results
```

### Expected Results

- Removable lines: 1000-5000
- Key files: `libavcodec/libx264.c`
- Execution time: 10-20 minutes (FFmpeg is large)

## Example 4: Discovering Features

Before analyzing a project, discover available features:

### Make-based Projects

```python
from prat.discovery import discover_features_make

features = discover_features_make("App/mosquitto")
print(f"Mosquitto features: {', '.join(features)}")

# Analyze each feature
for feature in features:
    result = run_complete_workflow("App/mosquitto", feature)
    if result.success:
        print(f"{feature}: {result.extraction_result.total_removable_lines} lines")
```

### Autotools Projects

```python
from prat.discovery import discover_features_autotools

features = discover_features_autotools("App/FFmpeg")
print(f"FFmpeg features: {', '.join(features[:10])}...")  # FFmpeg has many features
```

### CMake Projects

```python
from prat.discovery import discover_features_cmake

features = discover_features_cmake("path/to/cmake-project")
print(f"Available features: {', '.join(features)}")
```

## Example 5: Handling Errors and Checkpoints

PRAT saves checkpoints during execution. Use them to diagnose and resume:

```python
from prat.workflow import run_complete_workflow, resume_workflow

# Run workflow
result = run_complete_workflow("App/mosquitto", "TLS")

if not result.success:
    print(f"Failed at: {result.checkpoint.value}")
    print(f"Error: {result.error_message}")
    
    # Checkpoint saved automatically
    checkpoint_file = "App/mosquitto/workflow_checkpoint.json"
    
    # Fix the issue, then resume
    result = resume_workflow(
        checkpoint_file=checkpoint_file,
        project_path="App/mosquitto",
        feature="TLS"
    )
```

## Example 6: Custom Build Commands

For projects with non-standard build processes:

```python
from prat.compilation import compile_project, BuildSystem

# Specify build system explicitly
result = compile_project(
    project_path="my-project",
    feature="MY_FEATURE",
    enabled=True,
    build_system=BuildSystem.CMAKE
)
```

## Example 7: Batch Analysis

Analyze multiple features in one script:

```python
from prat.workflow import run_complete_workflow
from prat.discovery import discover_features_make

project = "App/mosquitto"
features = discover_features_make(project)

results = {}
for feature in features:
    print(f"\nAnalyzing {feature}...")
    result = run_complete_workflow(project, feature)
    
    if result.success:
        results[feature] = result.extraction_result.total_removable_lines
    else:
        results[feature] = None

# Print summary
print("\n" + "="*50)
print("Summary")
print("="*50)
for feature, lines in results.items():
    if lines is not None:
        print(f"{feature:20s}: {lines:6d} lines")
    else:
        print(f"{feature:20s}: FAILED")
```

## Example 8: Docker Demo Runner

Run all demos and generate comparison report:

```bash
# Build all demos
python3 src/demo-runner.py --build-all

# Run all demos
python3 src/demo-runner.py --run-all --output demo_results --report comparison.txt

# View report
cat comparison.txt
```

## Example 9: Validating Results

Validate demo results against expected values:

```python
from src.demo_runner import run_demo, EXPECTED_RESULTS

demo_name = "mosquitto-tls"
result = run_demo(demo_name, "output")

expected = EXPECTED_RESULTS[demo_name]

print(f"Demo: {demo_name}")
print(f"Actual lines: {result.removable_lines}")
print(f"Expected range: {expected.min_removable_lines}-{expected.max_removable_lines}")
print(f"Within range: {result.within_expected_range}")

if result.key_files_missing:
    print(f"Warning: Missing key files: {result.key_files_missing}")
```

## Example 10: Programmatic Docker Usage

Use Docker API directly for custom workflows:

```python
from prat.docker_runner import build_docker_image, run_docker_container
from pathlib import Path

# Build custom image
success = build_docker_image(
    dockerfile_path="docker/demo1/Dockerfile",
    image_name="my-prat-analysis:v1",
    build_context=".",
    build_args={"FEATURE": "TLS"},
    no_cache=True
)

if success:
    # Run with custom output directory
    output_dir = Path("custom_output").absolute()
    output_dir.mkdir(exist_ok=True)
    
    result = run_docker_container(
        image_name="my-prat-analysis:v1",
        volumes={str(output_dir): "/prat/output"},
        environment={"VERBOSE": "1"},
        timeout=3600
    )
    
    if result.success:
        print("Analysis complete!")
        print(result.stdout)
    else:
        print(f"Failed: {result.error_message}")
        print(result.stderr)
```

## Tips and Best Practices

### 1. Start Small

Begin with small, well-understood features:
```python
# Good first feature
result = run_complete_workflow("App/mosquitto", "TLS")

# Complex feature (may take longer)
result = run_complete_workflow("App/FFmpeg", "avcodec")
```

### 2. Use Test Suites

Running tests improves coverage:
```python
result = run_complete_workflow(
    project_path="App/mosquitto",
    feature="TLS",
    run_tests=True  # Better coverage
)
```

### 3. Check Intermediate Results

Don't wait for complete workflow - check intermediate steps:
```bash
# After compilation
ls App/mosquitto/src/*.gcno

# After coverage generation
ls coverage_files_WITH_TLS_yes/

# After diffing
ls diff_TLS/
```

### 4. Preserve Results

Save important results:
```python
import shutil

result = run_complete_workflow("App/mosquitto", "TLS")

if result.success:
    # Copy results to permanent location
    shutil.copytree(
        result.extraction_result.html_report_path,
        "saved_results/mosquitto_tls_report.html"
    )
```

### 5. Automate Validation

Create validation scripts:
```python
def validate_analysis(result, min_lines, max_lines):
    """Validate analysis results."""
    if not result.success:
        return False, "Workflow failed"
    
    lines = result.extraction_result.total_removable_lines
    
    if lines < min_lines:
        return False, f"Too few lines: {lines} < {min_lines}"
    
    if lines > max_lines:
        return False, f"Too many lines: {lines} > {max_lines}"
    
    return True, "Validation passed"

# Use it
result = run_complete_workflow("App/mosquitto", "TLS")
valid, message = validate_analysis(result, 500, 1500)
print(message)
```

## See Also

- [API Documentation](API.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)
- [Docker Demo Guide](../docker/README.md)
