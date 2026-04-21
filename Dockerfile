# =============================================================================
# THIRAMAI Genesis — multi-stage production image (CIS-aligned, non-root, minimal attack surface)
# =============================================================================
# Build:  docker build -t thiramai-genesis:latest .
# Run:    docker-compose / docker-compose.production.yml (never bake secrets; pass via env)
#
# Security model:
# - Multi-stage: compilers & build-only tools stay in builder; runtime has no gcc/make.
# - Single non-root UID for all processes (CIS 4.1, 4.6); no secrets in image ENV/ARG.
# - HEALTHCHECK hits HTTP only for the default API CMD; worker containers use the same
#   image with a different CMD and docker-compose healthchecks that use pgrep (see comment).
# =============================================================================

# -----------------------------------------------------------------------------
# Builder — dependency resolution, wheels, SBOM only. Not used as the running image.
# Pin base images to patch-level tags for reproducible builds (avoid implicit "latest").
# -----------------------------------------------------------------------------
FROM python:3.12.9-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# gcc + libpq-dev: required to build some wheels (e.g. psycopg2); stripped from runtime stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-base.txt requirements-production.txt ./

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Production runtime deps only (no dev/test tooling — see requirements-dev.txt).
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements-base.txt -r requirements-production.txt

# SBOM at build time; tool uninstalled so it is not present in the runtime venv (smaller, fewer packages).
RUN mkdir -p /app \
    && pip install cyclonedx-bom --quiet \
    && cyclonedx-py requirements requirements-base.txt -o /app/sbom.json --of JSON \
    && pip uninstall cyclonedx-bom -y

# -----------------------------------------------------------------------------
# Frontend build stage — Node only; output is static files copied into runtime (no Node in final image).
# -----------------------------------------------------------------------------
FROM node:20.18.3-bookworm-slim AS frontend

ARG SKIP_FRONTEND=0
WORKDIR /app/web/command_center

COPY web/command_center/package.json web/command_center/package-lock.json ./
RUN if [ "$SKIP_FRONTEND" != "1" ]; then npm ci; fi

COPY web/command_center/ ./
# Clear prior build output so Docker layers never ship stale cc-app.js / unhashed chunks from a cached tree.
RUN mkdir -p /app/static/command_center \
 && rm -rf /app/static/command_center/* \
 && if [ "$SKIP_FRONTEND" != "1" ]; then npm run build; else mkdir -p /app/static/command_center; fi

# -----------------------------------------------------------------------------
# Runtime — Python + libpq client + procps only; venv copied from builder; app runs as non-root.
# -----------------------------------------------------------------------------
FROM python:3.12.9-slim-bookworm AS runtime

# OCI / org labels: provenance for scanners and policy (supply chain; not a substitute for image signing).
LABEL maintainer="thiramai-team"
LABEL security.scan="required"
LABEL org.opencontainers.image.source="https://github.com/your-org/thiramai"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Intentionally no GUNICORN_WORKERS here: set at deploy time (compose/Kubernetes) to avoid baking infra policy.
# Default worker count remains in CMD via shell ${GUNICORN_WORKERS:-4}.

# libpq5: PostgreSQL client library for psycopg2 at runtime.
# procps: pgrep/ps used by docker-compose healthchecks when this image runs worker commands (no HTTP server).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . .
COPY --from=builder /app/sbom.json /app/sbom.json

# Overlay Vite build into static/command_center without clobbering committed assets when SKIP_FRONTEND=1.
ARG SKIP_FRONTEND=0
COPY --from=frontend /app/static/command_center /tmp/cc_frontend_build
RUN if [ "$SKIP_FRONTEND" != "1" ]; then \
      rm -rf ./static/command_center \
      && mkdir -p ./static/command_center \
      && cp -a /tmp/cc_frontend_build/. ./static/command_center/; \
    fi \
 && rm -rf /tmp/cc_frontend_build

# Baked deploy id for optional ``?v=`` on Command Center shell URLs (override at runtime via compose env).
ARG THIRAMAI_COMMAND_CENTER_BUILD_ID=
ENV THIRAMAI_COMMAND_CENTER_BUILD_ID=${THIRAMAI_COMMAND_CENTER_BUILD_ID}

# CIS 4.1 / 4.6: dedicated non-root user; fixed UID/GID for ownership mapping on volumes.
# /sbin/nologin: interactive shell logins disabled (service account pattern).
RUN groupadd --gid 10001 appuser \
    && useradd --create-home --uid 10001 --gid appuser --shell /sbin/nologin appuser \
    && chown -R appuser:appuser /app /opt/venv

USER appuser

EXPOSE 8000

# web: HTTP liveness check (Gunicorn on :8000)
# workers: process check via pgrep (no HTTP server) — use compose healthcheck when CMD is worker; this HEALTHCHECK applies to the default API image only.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4)"

# Gunicorn + Uvicorn workers; bind 0.0.0.0 only inside the container network namespace (publish via compose).
CMD ["/bin/sh", "-c", "exec gunicorn main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 -w ${GUNICORN_WORKERS:-4} --timeout 120 --graceful-timeout 30 --keep-alive 5 --access-logfile - --error-logfile -"]
