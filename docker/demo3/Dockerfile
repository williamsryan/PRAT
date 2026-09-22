# Dockerfile for PRAT Demo 3: FFmpeg DCA Decoder Feature Analysis
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
    toml==0.10.2

WORKDIR /prat

# Copy PRAT source code
COPY src/ /prat/src/

# Clone FFmpeg at pinned version (matches scripts/fetch-targets.sh)
RUN git clone --depth 1 --branch n5.1.4 \
    https://github.com/FFmpeg/FFmpeg.git /prat/App/FFmpeg && \
    test "$(git -C /prat/App/FFmpeg rev-parse HEAD)" = \
    "4729204c17f756e186d622060088371d10b34f7e"

ENV PROJECT_PATH=/prat/App/FFmpeg
ENV FEATURE=decoder=dca
ENV PATH="/usr/bin:${PATH}"

RUN mkdir -p /prat/output

# SCOPE SUBSTITUTION: the paper's `x264` removable code lives in the EXTERNAL
# libx264 library, which FFmpeg only links — PRAT compiles just the in-tree
# wrapper (libavcodec/libx264.c, ~549 lines), so it cannot see the feature's
# real footprint. To demonstrate PRAT on an FFmpeg feature whose code is fully
# in-tree, the demo analyzes the DTS (`dca`) decoder — a self-contained internal
# codec (7 dedicated files) removable via `--disable-decoder=dca`.
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/FFmpeg", \
     "--feature", "decoder=dca", \
     "--remove", \
     "--output", "/prat/output"]
