# Dockerfile for PRAT Demo 2: Mosquitto Bridge Feature Analysis
# This demo analyzes the Bridge feature in the Mosquitto MQTT broker

FROM python:3.11-slim-bookworm

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Keep package names stable but avoid exact apt revisions: Ubuntu archive
# revisions differ by architecture and date, which made the demo unbuildable.
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

# Install Python dependencies needed by the source-run demo
RUN pip3 install --no-cache-dir \
    toml==0.10.2

# Create working directory
WORKDIR /prat

# Copy PRAT source code
COPY src/ /prat/src/

# Fetch Mosquitto source (pinned version — matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch v2.0.15 \
    https://github.com/eclipse/mosquitto.git /prat/App/mosquitto

# Set environment variables
ENV PROJECT_PATH=/prat/App/mosquitto
ENV FEATURE=BRIDGE
ENV PATH="/usr/bin:${PATH}"

# Create output directory
RUN mkdir -p /prat/output

# Default command: Run complete PRAT workflow for Mosquitto Bridge
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/mosquitto", \
     "--feature", "BRIDGE", \
     "--output", "/prat/output"]
