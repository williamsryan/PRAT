# Dockerfile for PRAT Demo 7: AOM (libaom) Encoder Feature Analysis
# Self-contained — clones libaom inside the image

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    make \
    cmake \
    git \
    yasm \
    nasm \
    perl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

COPY src/ /prat/src/

# Clone AOM at pinned version
RUN git clone --depth 1 --branch v3.7.1 \
    https://aomedia.googlesource.com/aom /prat/App/aom

ENV PROJECT_PATH=/prat/App/aom
ENV FEATURE=CONFIG_AV1_ENCODER

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/aom", \
     "--feature", "CONFIG_AV1_ENCODER", \
     "--output", "/prat/output"]
