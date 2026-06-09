# PRAT Roadmap

This file tracks known follow-up work for the research prototype. It is not
required for the release demo path.

## Current Release Scope

The current package supports:

- Feature discovery for Make, CMake, Autotools, and Cargo projects
- Differential coverage collection using feature-enabled and feature-disabled builds
- Coverage diffing and feature-specific line extraction
- HTML, JSON, DOT, and batch-analysis reports
- Optional source removal and post-removal verification paths
- Docker demos for Mosquitto TLS, Mosquitto Bridge, and FFmpeg x264

The recommended review/demo path is:

```bash
make setup
make demo-release
```

`make demo-release` runs the Mosquitto TLS workflow in Docker and writes review
artifacts under `results/release-demo/mosquitto-tls/`.

## Known Follow-Up Work

- Add a separate Docker demo target that performs source removal and verification
  after feature identification.
- Validate the KLEE-based symbolic execution path inside the KLEE Docker image
  before presenting it as part of the primary workflow.
- Broaden adapter coverage beyond Mosquitto and FFmpeg.
- Improve type-checking coverage until `mypy src/prat/` is clean enough to make
  mandatory in release checks.
- Add an offline/self-contained feature graph mode that does not depend on a CDN.
