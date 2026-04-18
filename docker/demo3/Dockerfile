# Dockerfile for PRAT Demo 3: FFmpeg Feature Analysis
# This demo analyzes configurable features in the FFmpeg multimedia framework

FROM ubuntu:20.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Pin package versions for reproducibility
RUN apt-get update && apt-get install -y \
    gcc=4:9.3.0-1ubuntu2 \
    g++=4:9.3.0-1ubuntu2 \
    make=4.2.1-1.2 \
    autoconf=2.69-11.1 \
    automake=1:1.16.1-4ubuntu6 \
    libtool=2.4.6-14 \
    pkg-config=0.29.1-0ubuntu4 \
    gcov=4:9.3.0-1ubuntu2 \
    python3=3.8.2-0ubuntu2 \
    python3-pip=20.0.2-5ubuntu1.10 \
    perl=5.30.0-9ubuntu0.5 \
    git=1:2.25.1-1ubuntu3.11 \
    yasm=1.3.0-2build1 \
    nasm=2.14.02-1 \
    libx264-dev=2:0.155.2917+git0a84d98-2 \
    libx265-dev=3.2.1-1build1 \
    libvpx-dev=1.8.2-1build1 \
    libfdk-aac-dev=2.0.1-1 \
    libmp3lame-dev=3.100-3 \
    libopus-dev=1.3.1-0ubuntu1 \
    libvorbis-dev=1.3.6-2ubuntu1 \
    libtheora-dev=1.1.1+dfsg.1-15ubuntu2 \
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

# Fetch FFmpeg source (pinned version — matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch n5.1.4 \
    https://github.com/FFmpeg/FFmpeg.git /prat/App/FFmpeg

# Set environment variables
ENV PROJECT_PATH=/prat/App/FFmpeg
ENV FEATURE=x264
ENV GCOV=/usr/bin/gcov-9
ENV PATH="/usr/bin:${PATH}"

# Create output directory
RUN mkdir -p /prat/output

# Default command: Run complete PRAT workflow for FFmpeg x264 feature
# Note: Feature can be overridden via environment variable
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/FFmpeg", \
     "--feature", "${FEATURE}", \
     "--output", "/prat/output"]
