# PRAT Docker Demo Execution Guide

This guide explains how to build and run Docker-based PRAT demos for reproducible feature analysis.

## Overview

PRAT provides three Docker demos that showcase feature analysis on real projects:

1. **Demo 1**: Mosquitto TLS feature
2. **Demo 2**: Mosquitto Bridge feature  
3. **Demo 3**: FFmpeg x264 encoder feature

Each demo runs in an isolated container. Target project versions are pinned;
Ubuntu package names are fixed but exact apt revisions are not pinned because
archive revisions differ by architecture and date.

## Prerequisites

- Docker installed and running
- At least 4GB free disk space
- Internet connection (for first build only)

Verify Docker is available:
```bash
docker --version
```

## Demo Descriptions

### Demo 1: Mosquitto TLS Feature

Analyzes the TLS (Transport Layer Security) feature in Mosquitto MQTT broker.

- **Build time**: 5-10 minutes
- **Run time**: 2-5 minutes
- **Expected output**: 500-1500 removable lines
- **Key files**: `net.c`, `tls_mosq.c`

### Demo 2: Mosquitto Bridge Feature

Analyzes the Bridge feature that enables connecting multiple MQTT brokers.

- **Build time**: 5-10 minutes
- **Run time**: 2-5 minutes
- **Expected output**: 300-800 removable lines
- **Key files**: `bridge.c`

### Demo 3: FFmpeg x264 Encoder

Analyzes the x264 H.264 video encoder feature in FFmpeg.

- **Build time**: 15-30 minutes (FFmpeg is large)
- **Run time**: 10-20 minutes
- **Expected output**: 1000-5000 removable lines
- **Key files**: `libavcodec/libx264.c`

## Quick Start

### Option 1: Committee/review demo

From the repository root:

```bash
make demo-release
```

This builds and runs the Mosquitto TLS demo and writes artifacts to
`results/release-demo/mosquitto-tls/`, including `report.html`,
`manifest.json`, `demo_manifest.json`, and `container.log`.

### Option 2: Using Demo Runner

The demo runner script automates building, running, and validating demos.

**Build all demos:**
```bash
python3 src/demo-runner.py --build-all
```

**Run all demos:**
```bash
python3 src/demo-runner.py --run-all --output demo_results
```

**View comparison report:**
```bash
cat demo_report.txt
```

### Option 3: Manual Docker Commands

**Build a specific demo:**
```bash
docker build -f docker/demo1/Dockerfile -t prat-demo:mosquitto-tls .
```

**Run the demo:**
```bash
docker run --rm -v $(pwd)/demo_output:/prat/output prat-demo:mosquitto-tls
```

## Step-by-Step Instructions

### Step 1: Build Docker Images

Build individual demos:

```bash
# Demo 1: Mosquitto TLS
python3 src/demo-runner.py --build mosquitto-tls

# Demo 2: Mosquitto Bridge
python3 src/demo-runner.py --build mosquitto-bridge

# Demo 3: FFmpeg x264
python3 src/demo-runner.py --build ffmpeg-x264
```

Or build all at once:
```bash
python3 src/demo-runner.py --build-all
```

**Build options:**
- `--no-cache`: Force rebuild without using Docker cache

### Step 2: Run Demos

Run individual demos:

```bash
# Demo 1
python3 src/demo-runner.py --run mosquitto-tls --output results

# Demo 2
python3 src/demo-runner.py --run mosquitto-bridge --output results

# Demo 3
python3 src/demo-runner.py --run ffmpeg-x264 --output results
```

Or run all demos:
```bash
python3 src/demo-runner.py --run-all --output results
```

**Run options:**
- `--output DIR`: Specify output directory (default: `demo_output`)
- `--report FILE`: Specify report filename (default: `demo_report.txt`)

### Step 3: Verify Results

Check the comparison report:
```bash
cat demo_report.txt
```

Expected output format:
```
================================================================================
PRAT Demo Comparison Report
================================================================================

Demo: mosquitto-tls
--------------------------------------------------------------------------------
Description: Mosquitto TLS feature analysis
Status: PASS
Removable Lines: 1234
Expected Range: 500-1500
Within Range: YES
Files Analyzed: 45
Key Files Found: net.c, tls_mosq.c
Execution Time: 123.45s

...

================================================================================
Summary
================================================================================
Total Demos: 3
Passed: 3
Failed: 0
Success Rate: 100.0%
================================================================================
```

### Step 4: Inspect Detailed Results

Each demo creates a subdirectory with detailed results:

```bash
# View workflow checkpoint
cat results/mosquitto-tls/workflow_checkpoint.json | python3 -m json.tool

# View HTML report (if generated)
open results/mosquitto-tls/*.html

# View diff files
ls results/mosquitto-tls/diff_TLS/

# View coverage files
ls results/mosquitto-tls/coverage_files_WITH_TLS_yes/
```

## Verifying Reproducibility

Run the same demo multiple times and compare results:

```bash
# First run
python3 src/demo-runner.py --run mosquitto-tls --output run1

# Second run
python3 src/demo-runner.py --run mosquitto-tls --output run2

# Compare results
diff run1/mosquitto-tls/workflow_checkpoint.json run2/mosquitto-tls/workflow_checkpoint.json
```

Results should be identical (same line counts, same files).

## Troubleshooting

### Build Fails

**Issue**: Docker build fails with package errors

**Solution**:
```bash
# Rebuild without cache
python3 src/demo-runner.py --build mosquitto-tls --no-cache

# Or manually
docker build --no-cache -f docker/demo1/Dockerfile -t prat-demo:mosquitto-tls .
```

### Container Fails to Run

**Issue**: Container exits with error

**Solution**:
```bash
# Run container interactively to debug
docker run -it --rm prat-demo:mosquitto-tls /bin/bash

# Inside container, run workflow manually
python3 /prat/src/demo_workflow.py --project /prat/App/mosquitto --feature TLS
```

### Results Outside Expected Range

**Issue**: Line counts don't match expected range

**Explanation**: This is informational, not necessarily an error. Variations can occur due to:
- Different project versions
- Compiler optimizations
- Test suite coverage

**Action**: Manually verify results are reasonable by inspecting HTML report.

### Missing Output Files

**Issue**: Output directory is empty

**Solution**:
```bash
# Ensure volume mount uses absolute path
python3 src/demo-runner.py --run mosquitto-tls --output $(pwd)/results

# Check container logs
docker logs <container-id>
```

## Running on Custom Projects

To analyze your own project:

1. **Create a Dockerfile** based on demo templates
2. **Copy your project** into the container
3. **Set environment variables** for project path and feature
4. **Run the workflow**

Example Dockerfile:
```dockerfile
FROM ubuntu:20.04

# Install dependencies (same as demo Dockerfiles)
RUN apt-get update && apt-get install -y gcc make python3 python3-pip gcov

# Copy PRAT and your project
COPY src/ /prat/src/
COPY my-project/ /prat/my-project/

# Run analysis
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/my-project", \
     "--feature", "MY_FEATURE", \
     "--output", "/prat/output"]
```

## Performance Tips

### Faster Builds

Use Docker layer caching:
```bash
# First build is slow
python3 src/demo-runner.py --build mosquitto-tls

# Subsequent builds are fast (uses cache)
python3 src/demo-runner.py --build mosquitto-tls
```

### Parallel Demo Execution

Run demos in parallel:
```bash
# Terminal 1
python3 src/demo-runner.py --run mosquitto-tls --output results &

# Terminal 2
python3 src/demo-runner.py --run mosquitto-bridge --output results &

# Wait for both
wait
```

## Reproducibility Guarantees

PRAT Docker demos improve reproducibility through:

1. **Pinned language line**: Python 3.11 slim Debian image
2. **Stable package set**: Dockerfiles install a fixed set of Ubuntu packages
3. **Minimal Python dependency set**: Docker demos install only the Python
   packages needed by the source-run demo path
4. **Isolated environment**: No host dependencies
5. **Pinned target projects**: Mosquitto and FFmpeg versions are fixed

## Expected Results Reference

| Demo | Min Lines | Max Lines | Key Files | Time |
|------|-----------|-----------|-----------|------|
| mosquitto-tls | 500 | 1500 | net.c, tls_mosq.c | 2-5 min |
| mosquitto-bridge | 300 | 800 | bridge.c | 2-5 min |
| ffmpeg-x264 | 1000 | 5000 | libavcodec/libx264.c | 10-20 min |

## Next Steps

After running demos successfully:

1. Review HTML reports to understand feature-specific code
2. Examine DOT graphs to visualize file relationships
3. Try analyzing different features using the workflow API
4. Adapt demos for your own projects

## See Also

- [Main README](../README.md)
- [API Documentation](../docs/API.md)
- [Troubleshooting Guide](../docs/TROUBLESHOOTING.md)
- [Usage Examples](../docs/EXAMPLES.md)
