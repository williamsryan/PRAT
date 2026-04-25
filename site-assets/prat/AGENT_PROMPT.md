You are working on Ryan's personal portfolio site. Add a project/demo page for PRAT using the assets in this folder.

Project:
PRAT - Protocol Representation and Analysis Toolkit

Purpose:
PRAT is a research artifact and command-line toolkit for identifying feature-specific code in C/C++/Rust projects using differential coverage analysis. Given a project and a named feature, PRAT builds the project twice, once with the feature enabled and once disabled, runs coverage-producing workloads, diffs the coverage files, extracts lines only reached in the feature-enabled build, and generates reports that help an analyst inspect or remove that code.

Positioning:
- Frame this as a static research artifact demo, not a live code-execution service.
- Do not build a public upload form or arbitrary "run PRAT on my repo" feature.
- It is okay to show a "Run locally" or "Reproduce with Docker" command block.
- Mention that live analysis runs target build systems, so the public web demo uses pinned, precomputed outputs.
- Put it near Ryan's other PhD/research systems such as Wasm-V and Sentinel.

Use these local assets:
- `project-brief.md`: polished content and copy points.
- `mosquitto-tls-demo.json`: structured demo metrics from a real local PRAT smoke run.
- `pipeline.svg`: a portable visual of the analysis pipeline.

Suggested page sections:
1. Hero / header:
   Title: "PRAT"
   Subtitle: "Protocol Representation and Analysis Toolkit"
   One-sentence hook: "A research artifact for finding feature-specific code by comparing coverage from feature-on and feature-off builds."

2. Demo snapshot:
   Use the Mosquitto TLS metrics:
   - Target: Mosquitto v2.0.15
   - Feature: TLS
   - Result: 1,743 removable lines
   - Files affected: 18
   - Runtime: 9.49s on Ryan's local Mac smoke run
   - Top files: conf.c, net_mosq.c, net.c, security_default.c, client_shared.c

3. Pipeline:
   Embed or redraw `pipeline.svg`.
   Steps: discover feature, compile ON, run workload, collect coverage, compile OFF, run workload, diff coverage, extract/report.

4. Interactive/static report area:
   Build a compact table or bar chart from `mosquitto-tls-demo.json`.
   If the portfolio has a component for charts, use it. Otherwise, use a simple responsive table.

5. Artifact honesty:
   Include a small note:
   "This page uses precomputed artifacts because running untrusted build systems on a public server is not safe. The CLI/Docker workflow can reproduce the analysis locally."

6. Reproduce block:
   Show:
   ```bash
   git clone <repo-url>
   cd PRAT
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ./scripts/fetch-targets.sh mosquitto
   prat App/mosquitto TLS --output results/mosquitto-tls
   ```

Tone:
Clear, research-oriented, and concrete. Avoid marketing fluff. The page should make PRAT feel real by showing actual numbers, generated artifacts, and reproducibility commands.

Design:
Use the site's existing visual language. This is a technical artifact page, so prefer dense, legible sections over a splashy landing page. Good components: metric strip, pipeline diagram, results table, command block, and links/buttons to code or artifacts. If the site supports project tags, use: research artifact, program analysis, coverage, debloating, C/C++/Rust, reproducibility.
