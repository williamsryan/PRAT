# PRAT Project Brief

## Short Description

PRAT (Protocol Representation and Analysis Toolkit) is a research artifact for identifying feature-specific code in C/C++/Rust projects. It compiles a target project with a feature enabled and disabled, runs coverage-producing workloads, diffs the resulting coverage files, and reports the source lines associated with that feature.

## One-Liner

A differential coverage toolkit for finding the code that only appears when a feature is active.

## What It Demonstrates

- Feature discovery from build configuration files.
- Feature-on and feature-off builds with coverage instrumentation.
- Dynamic coverage collection using gcov or llvm-cov.
- Coverage diffing and extraction of feature-specific source lines.
- HTML, JSON, and DOT reports for inspection and follow-up analysis.
- Optional source removal and verification workflows for local experiments.

## Portfolio Framing

PRAT should be shown as a static, reproducible research artifact demo. The web page should not execute arbitrary submitted projects. Running PRAT means running build systems, compilers, and target workloads, so a public web version should use precomputed outputs from pinned targets.

## Demo Used For The Site

Target: Mosquitto v2.0.15

Feature: TLS

Smoke-run date: 2026-04-25

Local command:

```bash
prat App/mosquitto TLS --output /tmp/prat-smoke
```

Result:

- Workflow completed successfully.
- Total runtime: 9.49 seconds.
- Removable TLS-associated lines: 1,743.
- Files affected: 18.
- Reports generated: HTML, JSON, DOT, coverage directories, and diff files.

Top affected files:

| File | Removable Lines |
|---|---:|
| `conf.c` | 326 |
| `net_mosq.c` | 291 |
| `net.c` | 257 |
| `security_default.c` | 223 |
| `client_shared.c` | 160 |
| `options.c` | 155 |
| `handle_connect.c` | 102 |
| `password_mosq.c` | 77 |

## Suggested Caveat Copy

This web demo uses precomputed artifacts because PRAT's full workflow runs target build systems and workloads. That is appropriate for a local research artifact or controlled container, but not for arbitrary public execution on a personal site.

## Suggested CTA Copy

- View demo results
- Read the artifact notes
- Reproduce locally
- View source

## Suggested Tags

Research artifact, program analysis, coverage-guided analysis, debloating, C/C++/Rust, reproducibility.
