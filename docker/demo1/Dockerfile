# Dockerfile for PRAT Demo 1: Mosquitto TLS Feature Analysis
# Self-contained — clones Mosquitto inside the image (no local App/ needed)

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies (stable package names, no pinned apt revisions)
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
    xsltproc \
    docbook-xsl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies needed by demo workflow
RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

# Copy PRAT source code
COPY src/ /prat/src/

# Clone Mosquitto at pinned version (matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch v2.0.15 \
    https://github.com/eclipse/mosquitto.git /prat/App/mosquitto

ENV PROJECT_PATH=/prat/App/mosquitto
ENV FEATURE=TLS

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/mosquitto", \
     "--feature", "TLS", \
     "--output", "/prat/output"]
