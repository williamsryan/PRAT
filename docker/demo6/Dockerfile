# Dockerfile for PRAT Demo 6: Quiche FFDHE Feature Analysis
# Self-contained — clones Quiche inside the image
# Requires Rust toolchain for Cargo builds

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    make \
    cmake \
    git \
    curl \
    pkg-config \
    golang \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain (needed for Cargo builds + coverage) and the
# source-based coverage tooling. quiche 0.20.1's `ffdhe` is NOT a real Cargo
# feature in this version (codebase drift from the paper era); the demo
# analyzes a feature that genuinely exists — see CMD below.
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal && \
    . /root/.cargo/env && \
    rustup component add llvm-tools-preview && \
    cargo install cargo-llvm-cov --locked

ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

COPY src/ /prat/src/

# Clone Quiche at pinned version (with submodules — vendored BoringSSL lives in
# quiche/deps/boringssl as a git submodule and is required to build).
RUN git clone --depth 1 --branch 0.20.1 \
    https://github.com/cloudflare/quiche.git /prat/App/quiche && \
    cd /prat/App/quiche && \
    git submodule update --init --recursive --depth 1

ENV PROJECT_PATH=/prat/App/quiche/quiche
ENV FEATURE=qlog

RUN mkdir -p /prat/output

# CODEBASE DRIFT: the paper's `ffdhe` is not a Cargo feature in quiche 0.20.1
# (it is BoringSSL C config, not a Rust feature). We analyze `qlog` instead —
# a real, detectable feature with 63 `#[cfg(feature="qlog")]` sites across
# quiche/src, exercised by the crate's tests. The quiche crate lives in the
# `quiche/` subdir of the workspace.
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/quiche/quiche", \
     "--feature", "qlog", \
     "--output", "/prat/output"]
