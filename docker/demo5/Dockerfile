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
    curl \
    perl \
    perl-modules \
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
ENV FEATURE=content-filtered-topic

RUN mkdir -p /prat/output

# "content-filtered-topic" is one of the five OpenDDS features the paper
# actually analyzes (paper/results/code_removal.csv) and is a real DDS-3.25
# ./configure switch. The previous target, "SECURITY", is not a feature the
# paper reports, so there was no published value to compare its result against.
CMD ["python3", "/prat/src/demo_workflow.py", \
     "--project", "/prat/App/OpenDDS", \
     "--feature", "content-filtered-topic", \
     "--output", "/prat/output"]
