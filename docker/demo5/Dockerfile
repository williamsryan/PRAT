# Dockerfile for PRAT Demo 5: OpenDDS Security Feature Analysis
# Self-contained — clones OpenDDS inside the image

FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    g++ \
    make \
    cmake \
    perl \
    git \
    libssl-dev \
    libxerces-c-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    toml==0.10.2 \
    pandas>=1.3.0

WORKDIR /prat

COPY src/ /prat/src/

# Clone OpenDDS at pinned version
RUN git clone --depth 1 --branch DDS-3.25 \
    https://github.com/OpenDDS/OpenDDS.git /prat/App/OpenDDS

ENV PROJECT_PATH=/prat/App/OpenDDS
ENV FEATURE=SECURITY

RUN mkdir -p /prat/output

CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/OpenDDS", \
     "--feature", "SECURITY", \
     "--output", "/prat/output"]
