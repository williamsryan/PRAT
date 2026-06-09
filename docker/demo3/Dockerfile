# Dockerfile for PRAT Demo 3: FFmpeg x264 Feature Analysis
# Self-contained — clones FFmpeg inside the image (no local App/ needed)

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies (stable package names, no pinned apt revisions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    make \
    autoconf \
    automake \
    libtool \
    pkg-config \
    perl \
    git \
    yasm \
    nasm \
    libx264-dev \
    libx265-dev \
    libvpx-dev \
    libmp3lame-dev \
    libopus-dev \
    libvorbis-dev \
    libtheora-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies needed by demo workflow
RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

# Copy PRAT source code
COPY src/ /prat/src/

# Clone FFmpeg at pinned version (matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch n5.1.4 \
    https://github.com/FFmpeg/FFmpeg.git /prat/App/FFmpeg

ENV PROJECT_PATH=/prat/App/FFmpeg
ENV FEATURE=x264

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/FFmpeg", \
     "--feature", "x264", \
     "--output", "/prat/output"]
