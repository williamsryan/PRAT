# Dockerfile for PRAT KLEE environment
# Provides KLEE symbolic execution engine for test generation.
#
# Usage:
#   docker build -f docker/klee/Dockerfile -t prat-klee .
#   docker run --rm -v $(pwd):/work prat-klee klee --help
#
# Or via the symbolic module:
#   result = generate_symbolic_tests(..., use_docker=True)

FROM klee/klee:3.0

USER root

# Install additional tools for PRAT integration
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    gcov \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip3 install --no-cache-dir toml>=0.10.2

# Create work directory
WORKDIR /work

# Copy PRAT source
COPY src/prat/ /prat/src/prat/

# Default: show KLEE version
CMD ["klee", "--version"]
