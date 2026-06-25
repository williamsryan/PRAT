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
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

COPY src/ /prat/src/

# Clone azure-uamqp-c with submodules
# NOTE: The paper references date-tag "2024-01-22" which does NOT exist in the
# upstream repo (the repo is archived; newest date-tag is 2020-12-09). We pin to
# the latest stable release tag v1.2.0 for a real, reproducible ref.
RUN git clone --depth 1 --branch v1.2.0 \
    https://github.com/Azure/azure-uamqp-c.git /prat/App/azure-uamqp-c && \
    cd /prat/App/azure-uamqp-c && \
    git submodule update --init --recursive --depth 1

# azure-uamqp-c v1.2.0 predates OpenSSL 3.0. Its vendored azure-c-shared-utility
# calls APIs deprecated in OpenSSL 3.0 (PEM_read_bio_RSAPrivateKey, RSA_free,
# SSL_CTX_use_RSAPrivateKey) and compiles UNIX builds with an unconditional
# -Werror, so deprecation/const-qualifier warnings become hard errors on
# Debian Bookworm (OpenSSL 3.0). Strip -Werror so the library compiles; this
# does not alter program behavior, only warning severity.
RUN find /prat/App/azure-uamqp-c \( -name '*.cmake' -o -name 'CMakeLists.txt' \) \
    -exec sed -i 's/-Werror//g' {} +

ENV PROJECT_PATH=/prat/App/azure-uamqp-c
ENV FEATURE=use_wsio

RUN mkdir -p /prat/output

# NOTE: The real CMake toggle for WebSocket support in azure-uamqp-c is
# `use_wsio` (azure-c-shared-utility CMakeLists.txt). The paper's
# "USE_WEBSOCKETS" is NOT a recognized CMake variable — passing it produces
# CMake's "Manually-specified variables were not used by the project" warning
# and an identical enabled/disabled build. We use the real `use_wsio` flag.
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/azure-uamqp-c", \
     "--feature", "use_wsio", \
     "--output", "/prat/output"]
