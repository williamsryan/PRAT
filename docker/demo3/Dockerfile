# Dockerfile for PRAT Demo 3: FFmpeg Feature Analysis
# This demo analyzes configurable features in the FFmpeg multimedia framework

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

# Install Python dependencies needed by the source-run demo
RUN pip3 install --no-cache-dir \
    toml==0.10.2

# Create working directory
WORKDIR /prat

# Copy PRAT source code
COPY src/ /prat/src/

# Fetch FFmpeg source (pinned version — matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch n5.1.4 \
    https://github.com/FFmpeg/FFmpeg.git /prat/App/FFmpeg

# Set environment variables
ENV PROJECT_PATH=/prat/App/FFmpeg
ENV FEATURE=x264
ENV PATH="/usr/bin:${PATH}"

# Create output directory
RUN mkdir -p /prat/output

# Default command: Run complete PRAT workflow for FFmpeg x264 feature
# Note: Feature can be overridden via environment variable
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/FFmpeg", \
     "--feature", "x264", \
     "--output", "/prat/output"]
