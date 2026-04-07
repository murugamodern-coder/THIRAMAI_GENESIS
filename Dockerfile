# THIRAMAI Genesis — multi-stage production image (Gunicorn + Uvicorn workers)
#
# Build:  docker build -t thiramai-genesis:latest .
# Run:    see docker-compose.yml or docker-compose.production.yml
#
# Override worker count:  -e GUNICORN_WORKERS=4
# Dev single-process (no Gunicorn): docker run ... uvicorn main:app --host 0.0.0.0 --port 8000

# -----------------------------------------------------------------------------
# Builder: compile/install wheels into a virtualenv (keeps runtime image slim).
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt requirements-production.txt ./

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt -r requirements-production.txt

# -----------------------------------------------------------------------------
# Command Center React (Vite → static/command_center); optional skip: docker build --build-arg SKIP_FRONTEND=1 .
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend

ARG SKIP_FRONTEND=0
WORKDIR /app/web/command_center

COPY web/command_center/package.json web/command_center/package-lock.json ./
RUN if [ "$SKIP_FRONTEND" != "1" ]; then npm ci; fi

COPY web/command_center/ ./
RUN if [ "$SKIP_FRONTEND" != "1" ]; then npm run build; else mkdir -p /app/static/command_center; fi

# -----------------------------------------------------------------------------
# Runtime: no compiler; libpq client only.
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    GUNICORN_WORKERS=4

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . .

ARG SKIP_FRONTEND=0
COPY --from=frontend /app/static/command_center ./static/command_center

RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app /opt/venv
USER appuser

EXPOSE 8000

# Liveness: JSON from GET / when Accept: application/json (matches smoke tests)
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4)"

# Gunicorn supervises multiple Uvicorn workers (production throughput).
CMD ["/bin/sh", "-c", "exec gunicorn main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 -w ${GUNICORN_WORKERS:-4} --timeout 120 --graceful-timeout 30 --keep-alive 5 --access-logfile - --error-logfile -"]
