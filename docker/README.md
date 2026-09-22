# PRAT Docker Demos

Self-contained source-pinned compatibility demos for all seven paper evaluation codebases. Each image
clones and verifies an exact target commit, then maps, removes, rebuilds, and tests one feature.

## Quick Start

```bash
# Build and run all 8 demos:
make docker-build
make docker-run
cat results/demo_report.txt

# Or individually:
make docker-demo-mosquitto-tls
make docker-demo-mosquitto-bridge
make docker-demo-ffmpeg
make docker-demo-uamqp
make docker-demo-opendds
make docker-demo-quiche
make docker-demo-rav1e
make docker-demo-aom
```

## Demo Overview

| # | Demo Name | Project | Feature | Build System | Paper reference | Time |
|---|---|---|---|---|---|---|
| 1 | `mosquitto-tls` | Mosquitto v2.0.15 | TLS | Make | 790 LOC | 2–5 min |
| 2 | `mosquitto-bridge` | Mosquitto v2.0.15 | Bridge | Make | 640 LOC | 2–5 min |
| 3 | `ffmpeg-dca` | FFmpeg n5.1.4 | `decoder=dca` | Autotools | no paper value | 10–20 min |
| 4 | `uamqp-websockets` | azure-uamqp-c | `use_wsio` | CMake | paper: 26 | 5–10 min |
| 5 | `opendds-content-filtered-topic` | OpenDDS DDS-3.25 | `content-filtered-topic` | MPC | paper: 73 | 10–20 min |
| 6 | `quiche-qlog` | Quiche 0.20.1 | qlog | Cargo | no paper value | 5–15 min |
| 7 | `rav1e-serialize` | rav1e v0.7.1 | serialize | Cargo | no paper value | 5–15 min |
| 8 | `aom-encoder` | AOM v3.7.1 | CONFIG_AV1_ENCODER | CMake | no paper value | 15–30 min |

## Prerequisites

- Docker installed and running (`docker --version`)
- At least 8GB free disk space; use `--cleanup` to remove each image after its run
- Internet connection (first build only — images clone git repos)

## Using the Demo Runner

```bash
# Build a specific demo:
python3 src/demo-runner.py --build mosquitto-tls

# Run a specific demo:
python3 src/demo-runner.py --run mosquitto-tls --output results/

# Build all:
python3 src/demo-runner.py --build-all

# Run all with comparison report:
python3 src/demo-runner.py --run-all --output results/ --report results/demo_report.txt
```

## Manual Docker Commands

```bash
# Build:
docker build -f docker/demo1/Dockerfile -t prat-demo:mosquitto-tls .

# Run (mounts output volume):
docker run --rm -v $(pwd)/results:/prat/output prat-demo:mosquitto-tls

# Interactive debugging:
docker run -it --rm prat-demo:mosquitto-tls /bin/bash
```

## Output Artifacts

Each demo produces in its output directory:
- `workflow_checkpoint.json` — Full results with line counts and timing
- `report.html` — Human-readable HTML report
- `report.json` — Machine-readable JSON report
- `FDG.dot` — Feature dependency graph (Graphviz DOT format)
- `manifest.json` — Build environment and configuration metadata
- `coverage_files_WITH_*_yes/` — Coverage with feature enabled
- `coverage_files_WITH_*_no/` — Coverage with feature disabled
- `diff_*/` — Unified diff files

## Verifying Results

```bash
# Check the comparison report:
cat results/demo_report.txt

# Parse a specific checkpoint:
python3 -c "
import json
data = json.load(open('results/docker/mosquitto-tls/workflow_checkpoint.json'))
print(f'Lines: {data[\"extraction_result\"][\"total_removable_lines\"]}')
print(f'Files: {len(data[\"extraction_result\"][\"file_line_counts\"])}')
"
```

## Paper Alignment

These demos cover the seven codebases in the paper. The paper does not publish the exact source
revisions used in 2021, so the pinned modern targets are compatibility checks rather than exact
numerical reproductions.
> Williams et al., "Guided Feature Identification and Removal for Resource-constrained Firmware," ACM TOSEM 2021 (doi:10.1145/3487568)

See [docs/PAPER_ALIGNMENT.md](../docs/PAPER_ALIGNMENT.md) for section-by-section code mapping.

## Troubleshooting

**Build fails with apt errors**: Images use `--no-install-recommends` with stable package names. If a package is unavailable in your architecture, try `--no-cache`:
```bash
python3 src/demo-runner.py --build mosquitto-tls --no-cache
```

**Container exits with error**: Run interactively to debug:
```bash
docker run -it --rm prat-demo:mosquitto-tls /bin/bash
python3 /prat/src/demo_workflow.py --project /prat/App/mosquitto --feature TLS --output /prat/output
```

**Observed count differs from the paper**: The report shows the deviation as context. The paper
does not publish the original source revisions, so the validator checks the evidence chain rather
than applying an invented range to a later release.
