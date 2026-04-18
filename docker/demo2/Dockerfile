# Dockerfile for PRAT Demo 2: Mosquitto Bridge Feature Analysis
# This demo analyzes the Bridge feature in the Mosquitto MQTT broker

FROM ubuntu:20.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Pin package versions for reproducibility
RUN apt-get update && apt-get install -y \
    gcc=4:9.3.0-1ubuntu2 \
    g++=4:9.3.0-1ubuntu2 \
    make=4.2.1-1.2 \
    cmake=3.16.3-1ubuntu1 \
    llvm-9=1:9.0.1-12 \
    clang-9=1:9.0.1-12 \
    python3=3.8.2-0ubuntu2 \
    python3-pip=20.0.2-5ubuntu1.10 \
    perl=5.30.0-9ubuntu0.5 \
    git=1:2.25.1-1ubuntu3.11 \
    libssl-dev=1.1.1f-1ubuntu2.20 \
    libcjson-dev=1.7.12-1 \
    libwebsockets-dev=3.2.1-3 \
    uuid-dev=2.34-0.1ubuntu9.4 \
    xsltproc=1.1.34-4ubuntu0.1 \
    docbook-xsl=1.79.1+dfsg-2ubuntu3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies with pinned versions
RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas==1.3.5 \
    numpy==1.21.6

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
ENV LLVM_COV=/usr/bin/llvm-cov-9
ENV PATH="/usr/lib/llvm-9/bin:${PATH}"

# Create output directory
RUN mkdir -p /prat/output

# Default command: Run complete PRAT workflow for Mosquitto Bridge
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/mosquitto", \
     "--feature", "BRIDGE", \
     "--output", "/prat/output"]
