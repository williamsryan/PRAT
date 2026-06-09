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
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain (needed for Cargo builds + coverage)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal && \
    . /root/.cargo/env && \
    rustup component add llvm-tools-preview

ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

COPY src/ /prat/src/

# Clone Quiche at pinned version
RUN git clone --depth 1 --branch 0.20.1 \
    https://github.com/cloudflare/quiche.git /prat/App/quiche

ENV PROJECT_PATH=/prat/App/quiche
ENV FEATURE=ffdhe

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/quiche", \
     "--feature", "ffdhe", \
     "--output", "/prat/output"]
