# Dockerfile for PRAT Demo 8: rav1e serialization feature analysis

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    clang \
    make \
    cmake \
    git \
    curl \
    pkg-config \
    nasm \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable --profile minimal && \
    . /root/.cargo/env && \
    rustup component add llvm-tools-preview && \
    cargo install cargo-llvm-cov --locked

ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip3 install --no-cache-dir \
    toml==0.10.2

WORKDIR /prat

COPY src/ /prat/src/

RUN git clone --depth 1 --branch v0.7.1 \
    https://github.com/xiph/rav1e.git /prat/App/rav1e && \
    test "$(git -C /prat/App/rav1e rev-parse HEAD)" = \
    "a8d05d0c43826a465b60dbadd0ab7f1327d75371"

ENV PROJECT_PATH=/prat/App/rav1e
ENV FEATURE=serialize

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/rav1e", \
     "--feature", "serialize", \
     "--remove", \
     "--output", "/prat/output"]
