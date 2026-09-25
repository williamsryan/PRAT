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

### `Compilation failed (B_all)`: a library for some option is missing

`B_all` enables every discovered option, so it needs every optional dependency: for Mosquitto,
libwebsockets, c-ares (`SRV`), jemalloc, libsystemd, libwrap, cJSON. Install them (the Docker
images do), or leave the options this environment cannot compile out of `F` explicitly:

```bash
prat App/mosquitto TLS --skip-feature SRV --skip-feature DLT --skip-feature JEMALLOC
```

The exclusion is recorded in the checkpoint as `features_excluded`; the analyzed feature cannot be
skipped. On macOS, Mosquitto's `PLUGINS`, `EPOLL`, `DLT`, `SYSTEMD` and `USE_LIBWRAP` options do
not build at all and must be skipped.

### `Exact removal incomplete: ... one or more mapped ranges were syntactically unsafe`

The balance guard declined runs in `D_f` whose removal would leave unbalanced delimiters, and
`require_complete` (the default) fails the removal and restores the tree rather than remove part
of `D_f`. The declined ranges are in `RemovalResult.skipped_unbalanced`. This is usually a
coverage symptom: `if (x) {` reached `D_f` because `T` executed it under `B_all`, but the body
never ran (so, per the paper, it stays) and the closing brace is not an executable line. A larger
`T` (`--symbolic`, or more commands in the adapter's `get_test_plan()`) is the fix; the local
two-session Mosquitto plan on macOS reaches about 20% line coverage and declines roughly half of
`D_TLS` for this reason.

## Mapping Issues

The mapping is `D_f = L_all \ L_f`: the lines executed under `T` in the all-features build
`B_all` that are not executed in the all-but-`f` build `B_f`. There is no textual diff of gcov
files and no `#####` selection rule; a line that is compiled but never run (`#####`) is kept in
both builds, by design. See `docs/PAPER_ALIGNMENT.md` §C1.

### `|D_f| = 0` (nothing mapped)

**Diagnosis:**
1. `T` never reaches the feature's code, so it is absent from `L_all` as well as `L_f`
2. The feature flag does not change what is compiled or executed
3. The feature is runtime-configured rather than compile-time

**Solution:**
1. Check the line coverage `T` achieved against `B_all`, printed after the mapping step and stored
   as `coverage_percent_enabled` in `workflow_checkpoint.json`. If it is low, `T` needs to
   exercise more of the program: add tests to the adapter's `get_test_plan()`, or generate `S`
   with `--symbolic`.
2. Verify the flag changes the build (`mapping_build_states` in the checkpoint shows the exact
   configuration of each build):
```bash
ls -lh App/mosquitto/src/mosquitto     # sizes should differ between the two builds
```
3. Inspect the two coverage sets directly (`--batch` labels the baseline
   `coverage_files_all_features/` instead):
```bash
ls coverage_files_WITH_TLS_yes/ coverage_files_WITH_TLS_no/
grep -c -v '#####\|^ *-:' coverage_files_WITH_TLS_yes/net.c.gcov   # executed lines
```

### Tests in `T` fail against `B_f`

**Symptom:** `N test command(s) in T could not run against B_TLS and contributed no coverage`

This is expected, not an error. `T` is fixed (Algorithm 1 line 3) and runs unchanged against
every build, so the tests that exercise `f` cannot pass in a build without `f`. Those commands are
listed in `tests_not_run_in_b_f` (workflow checkpoint) or `tests_not_run` (batch checkpoint).
Coverage for `L_f` comes from the rest of `T`.

It becomes a problem only if *every* command fails, because then `L_f` is empty and `D_f = L_all`.
The run fails in that case (`Coverage generation failed (disabled)`). Fix the adapter's
`get_test_plan()` so at least part of `T` runs on every build; the Mosquitto adapter's plain-listener
session alongside its TLS session is the pattern.

### Tests in `T` fail against `B_all`

**Symptom:** `Coverage generation failed (enabled): 1 command(s) failed`

Not tolerated: `L_all` is the baseline every `D_f` is measured against, so every command of `T`
must pass there. Run the failing command by hand against the instrumented build and fix the
workload or the environment.

### `The test plan executed against B_f differs from the one executed against B_all`

The digest recorded for each build is computed from the commands that actually ran. This
message means an adapter or a caller changed the plan between builds; `get_test_plan()` must not
depend on which feature is being analysed.

### File Matching Fails

**Symptom:** `No parseable coverage in ...`

**Diagnosis:**
gcov produced no `.gcov` files, or produced them somewhere the collector does not look.

**Solution:**
Check the coverage directory structure:
```bash
ls coverage_files_WITH_TLS_yes/
ls coverage_files_WITH_TLS_no/
# Files should have the same base names; each maps to one source file
```

## Extraction Issues

### No Removable Lines Found

**Symptom:** `Identified 0 removable lines`

**Diagnosis:**
`D_f` was empty (see "Mapping Issues" above), or every run in `D_f` was declined by the
delimiter-balance guard (`RemovalResult.skipped_unbalanced`).

**Solution:**
Read the mapping report, which lists every line in `D_f` with its state in both builds:
```bash
ls <output-dir>/report.html <output-dir>/coverage_comparison/
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

### Observed Count Differs from the Paper

**Symptom:** The source-pinned result differs from the historical paper value.

**Diagnosis:**
1. Project version may differ
2. Compiler version may differ
3. Feature implementation changed

**Solution:**
Use strict validation to verify provenance, dynamic execution, mapped-line
removal, and post-removal behavior. The paper does not publish its exact source
revision, so the artifact does not invent a numerical acceptance range:
```bash
python3 scripts/validate_paper_results.py demo_output \
  --target mosquitto-tls --strict
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
