# THIRAMAI — headless pytest sandbox (micro-kernel / Self-Coder)
#
# Build from repository root:
#   docker build -f docker/sandbox/Dockerfile -t thiramai-sandbox:latest .
#
# Runtime mounts the host repo at /workspace (read-only) and patch dir at /patches (read-only).

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends patch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements-base.txt requirements-dev.txt /tmp/req/
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/req/requirements-dev.txt

# Idle image; commands supplied by Docker SDK from the host.
CMD ["python", "-c", "print('thiramai-sandbox ready')"]
