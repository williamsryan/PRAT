# PRAT Troubleshooting Guide

This guide helps resolve common issues when using PRAT.

## Installation Issues

### Missing Python Packages

**Symptom:** `ModuleNotFoundError: No module named 'toml'` or similar

**Solution:**
```bash
pip3 install -r requirements.txt
```

### Missing Build Tools

**Symptom:** `Missing dependencies: gcc, make`

**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get install gcc g++ make cmake

# macOS
brew install gcc make cmake

# Fedora/RHEL
sudo dnf install gcc gcc-c++ make cmake
```

### Missing Coverage Tools

**Symptom:** `Missing dependencies: gcov, llvm-cov`

**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get install gcov llvm-9

# macOS
brew install llvm

# Fedora/RHEL
sudo dnf install gcc llvm
```

## Compilation Issues

### Compilation Fails with Feature Enabled

**Symptom:** `Compilation failed (enabled): make: *** [target] Error 1`

**Diagnosis:**
1. Verify the project builds normally without PRAT
2. Check feature flag syntax matches project's build system
3. Review compilation logs for specific errors

**Solution:**
```bash
# Test manual compilation
cd App/mosquitto
make clean
make WITH_TLS=yes

# If this fails, fix project issues before using PRAT
```

### Wrong Feature Flag Format

**Symptom:** Feature flag has no effect on compilation

**Common Mistakes:**
- Make projects: Use `WITH_FEATURE=yes/no` not `--enable-feature`
- Autotools: Use `--enable-feature` not `WITH_FEATURE=yes`
- CMake: Use `-DCONFIG_FEATURE=ON/OFF` not `WITH_FEATURE=yes`

**Solution:** Check project documentation for correct flag format

### Coverage Flags Not Applied

**Symptom:** No .gcno files generated during compilation

**Solution:**
Ensure CFLAGS includes coverage flags:
```bash
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov"
```

## Coverage Generation Issues

### No Coverage Files Generated

**Symptom:** `Coverage generation failed: No .gcov files found`

**Diagnosis:**
1. Check if .gcno files exist (created during compilation)
2. Check if .gcda files exist (created during execution)
3. Verify gcov/llvm-cov is in PATH

**Solution:**
```bash
# Check for .gcno files
find App/mosquitto -name "*.gcno"

# Check for .gcda files
find App/mosquitto -name "*.gcda"

# If .gcda missing, run tests to execute code
prat App/mosquitto TLS --tests
```

### Wrong Coverage Tool

**Symptom:** `gcov: unrecognized option '--version'`

**Solution:**
Specify correct coverage tool:
```python
# For projects compiled with clang
from prat.coverage import generate_coverage
result = generate_coverage(
    project_path="App/mosquitto",
    feature="TLS",
    enabled=True,
    coverage_tool="llvm-cov"
)
```

### Permission Denied

**Symptom:** `Permission denied: 'coverage_files_WITH_TLS_yes'`

**Solution:**
```bash
# Ensure write permissions in project directory
chmod -R u+w App/mosquitto

# Or run with sudo (not recommended)
sudo prat ...
```

## Diff Analysis Issues

### All Diffs Are Empty

**Symptom:** `Generated 0 diff files` or all diffs removed as empty

**Diagnosis:**
Feature may not affect code execution paths

**Solution:**
1. Run with test suite to execute more code:
```bash
prat App/mosquitto TLS --tests
```

2. Verify feature flag actually changes compilation:
```bash
# Check binary sizes differ
ls -lh App/mosquitto/src/mosquitto
```

3. Check if feature is runtime-only (not compile-time)

### File Matching Fails

**Symptom:** `No matching coverage files found`

**Diagnosis:**
Coverage file names don't match between enabled/disabled builds

**Solution:**
Check coverage directory structure:
```bash
ls coverage_files_WITH_TLS_yes/
ls coverage_files_WITH_TLS_no/

# Files should have same base names
```

## Extraction Issues

### No Removable Lines Found

**Symptom:** `Identified 0 removable lines`

**Diagnosis:**
1. Feature may be very small
2. Diffs may not contain `#####` markers
3. Feature may be runtime-only

**Solution:**
Manually inspect diff files:
```bash
grep "#####" diff_TLS/*.gcov
```

### HTML Report Not Generated

**Symptom:** `html_report_path: None`

**Diagnosis:**
Extraction may have failed or found no results

**Solution:**
Check extraction logs for errors:
```python
result = extract_features(...)
if not result.success:
    print(result.error_message)
```

## Docker Issues

### Docker Not Available

**Symptom:** `Docker is not available on this system`

**Solution:**
Install Docker:
- Linux: https://docs.docker.com/engine/install/
- macOS: https://docs.docker.com/desktop/install/mac-install/
- Windows: https://docs.docker.com/desktop/install/windows-install/

### Docker Build Fails

**Symptom:** `Docker build failed with exit code 1`

**Diagnosis:**
1. Check Dockerfile syntax
2. Verify base image is available
3. Check network connectivity for package downloads

**Solution:**
```bash
# Build with verbose output
docker build -f docker/demo1/Dockerfile -t prat-demo:test . --progress=plain

# Check Docker daemon is running
docker ps
```

### Container Timeout

**Symptom:** `Container execution timed out after 1800s`

**Solution:**
Increase timeout:
```python
result = run_docker_container(
    image_name="prat-demo:mosquitto-tls",
    timeout=3600  # 1 hour
)
```

### Volume Mount Issues

**Symptom:** Output files not appearing on host

**Solution:**
Use absolute paths for volume mounts:
```python
import os
result = run_docker_container(
    image_name="prat-demo:mosquitto-tls",
    volumes={
        os.path.abspath("./output"): "/prat/output"
    }
)
```

## Performance Issues

### Compilation Takes Too Long

**Solution:**
Use parallel make:
```bash
# Edit compilation.py to use make -j
make -j$(nproc) WITH_TLS=yes
```

### Coverage Generation Slow

**Solution:**
Process files in parallel (see API.md for example)

### Large Diff Files

**Symptom:** Diff directory is very large

**Solution:**
This is normal for large projects. Consider:
- Analyzing smaller features
- Filtering to specific source directories
- Using compression for storage

## Validation Issues

### Results Don't Match Expected Range

**Symptom:** `Within range: NO`

**Diagnosis:**
1. Project version may differ
2. Compiler version may differ
3. Feature implementation changed

**Solution:**
This is informational - verify results manually:
```bash
# Check key files were analyzed
grep "tls_mosq.c" demo_output/mosquitto-tls/workflow_checkpoint.json

# Inspect HTML report
open demo_output/mosquitto-tls/*.html
```

### Key Files Missing

**Symptom:** `Key files missing: net.c, tls_mosq.c`

**Diagnosis:**
Files may have been renamed or removed in project

**Solution:**
Check project structure:
```bash
find App/mosquitto -name "tls*.c"
find App/mosquitto -name "net.c"
```

## Getting Help

If you encounter issues not covered here:

1. Check the API documentation: `docs/API.md`
2. Review example usage in `src/demo_workflow.py`
3. Examine checkpoint files for detailed error information
4. Run with verbose logging (if implemented)

## Common Workflow

For most issues, this diagnostic workflow helps:

1. **Verify dependencies:**
```python
from prat.environment import verify_dependencies
print(verify_dependencies())
```

2. **Test manual compilation:**
```bash
cd <project>
make clean
make WITH_FEATURE=yes
```

3. **Check coverage files:**
```bash
find . -name "*.gcno"
find . -name "*.gcda"
```

4. **Inspect intermediate results:**
```bash
ls coverage_files_WITH_FEATURE_yes/
ls diff_FEATURE/
```

5. **Review checkpoint:**
```bash
cat workflow_checkpoint.json | python3 -m json.tool
```
