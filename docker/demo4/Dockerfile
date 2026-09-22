# Dockerfile for PRAT Demo 4: azure-uamqp-c WebSockets Feature Analysis
# Self-contained — clones azure-uamqp-c inside the image

# NOTE: azure-uamqp-c v1.2.0 (2020-era) targets OpenSSL 1.1.x. Its OpenSSL
# version guards cap at "< 0x20000000L", so OpenSSL 3.0 (bookworm) falls into a
# legacy code path that uses now-opaque SSL_CTX fields and fails to compile.
# We therefore use the bullseye base (OpenSSL 1.1.1) which satisfies the guard
# and compiles the upstream source UNMODIFIED. Python stays at 3.11.
FROM python:3.11-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    make \
    cmake \
    git \
    libssl-dev \
    libcurl4-openssl-dev \
    uuid-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    toml==0.10.2

WORKDIR /prat

COPY src/ /prat/src/

# Clone azure-uamqp-c at an immutable commit and initialize its dependencies.
RUN git clone --depth 1 --branch v1.2.0 \
    https://github.com/Azure/azure-uamqp-c.git /prat/App/azure-uamqp-c && \
    test "$(git -C /prat/App/azure-uamqp-c rev-parse HEAD)" = \
    "9701f09a4db40afb53f5086662be64e8fac78bbf" && \
    cd /prat/App/azure-uamqp-c && \
    git submodule update --init --recursive --depth 1

ENV PROJECT_PATH=/prat/App/azure-uamqp-c
ENV FEATURE=use_wsio

RUN mkdir -p /prat/output

# `use_wsio` is the CMake toggle for WebSocket support in azure-uamqp-c, and is
# the option the paper reports for this feature (paper/results/code_removal.csv
# lists "use_wsio", 26 lines). "USE_WEBSOCKETS" appeared in earlier revisions of
# this repo but is not a recognized CMake variable and is not the paper's name
# for the option either.
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/azure-uamqp-c", \
     "--feature", "use_wsio", \
     "--remove", \
     "--output", "/prat/output"]
