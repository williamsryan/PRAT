# Dockerfile for PRAT Demo 1: Mosquitto TLS Feature Analysis
# Self-contained — clones Mosquitto inside the image (no local App/ needed)

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies (stable package names, no pinned apt revisions)
# Algorithm 1 builds B_all with every discovered option on, so the image needs
# the libraries the non-default Mosquitto options link against (SRV -> c-ares,
# JEMALLOC, SYSTEMD, WRAP), plus CUnit for the unit tests that form T (make utest).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    make \
    cmake \
    perl \
    git \
    libssl-dev \
    libcjson-dev \
    libwebsockets-dev \
    uuid-dev \
    libc-ares-dev \
    libjemalloc-dev \
    libsystemd-dev \
    libwrap0-dev \
    libcunit1-dev \
    xsltproc \
    docbook-xsl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies needed by demo workflow
RUN pip3 install --no-cache-dir \
    toml==0.10.2

WORKDIR /prat

# Copy PRAT source code
COPY src/ /prat/src/

# Clone Mosquitto at pinned version (matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch v2.0.15 \
    https://github.com/eclipse/mosquitto.git /prat/App/mosquitto && \
    test "$(git -C /prat/App/mosquitto rev-parse HEAD)" = \
    "b0277869d9806f6fab8e1bc11c4a4987c9a79ded"

ENV PROJECT_PATH=/prat/App/mosquitto
ENV FEATURE=TLS
ENV PATH="/usr/bin:${PATH}"

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/mosquitto", \
     "--feature", "TLS", \
     "--remove", \
     "--output", "/prat/output"]
