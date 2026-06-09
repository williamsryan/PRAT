# Dockerfile for PRAT Demo 4: azure-uamqp-c WebSockets Feature Analysis
# Self-contained — clones azure-uamqp-c inside the image

FROM python:3.11-slim-bookworm

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
RUN git clone --depth 1 --branch 2024-01-22 \
    https://github.com/Azure/azure-uamqp-c.git /prat/App/azure-uamqp-c && \
    cd /prat/App/azure-uamqp-c && \
    git submodule update --init --recursive --depth 1

ENV PROJECT_PATH=/prat/App/azure-uamqp-c
ENV FEATURE=USE_WEBSOCKETS

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/azure-uamqp-c", \
     "--feature", "USE_WEBSOCKETS", \
     "--output", "/prat/output"]
