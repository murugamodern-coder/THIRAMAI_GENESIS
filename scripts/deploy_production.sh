#!/usr/bin/env bash
# THIRAMAI GENESIS — final production deployment (Linux / macOS / Git Bash on Windows)
#
# Sequence (owner specification):
#   1. python scripts/go_live_checklist.py
#   2. alembic upgrade head
#   3. docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
#   4. curl GET /health/ready until success
#   5. notify: "Deployment Successful"
#
# IMPORTANT — first-time / cold stack:
#   go_live_checklist.py requires active Redis heartbeats from job_worker OR alert_worker.
#   On a host where workers are not yet running, step 1 will fail. Bootstrap once with:
#     export THIRAMAI_SKIP_GO_LIVE_CHECKLIST=1
#     ./scripts/deploy_production.sh
#   then after workers are healthy, run: python scripts/go_live_checklist.py
#   Or: bring the stack up first (compose + alembic), then run only the checklist as a gate.
#
# Non-interactive Docker exec (avoids TTY freezes in SSH/IDE):
#   docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic current
# Stack checks: docs/OPS_TERMINAL_AND_DOCKER.md — scripts/verify_stack.sh / verify_stack.ps1
#
# Usage:
#   chmod +x scripts/deploy_production.sh
#   ./scripts/deploy_production.sh
#
# Optional:
#   THIRAMAI_ENV_FILE=/path/.env.production  WEB_PORT=8000  PYTHON=/path/python

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${THIRAMAI_ENV_FILE:-.env.production}"
COMPOSE_FILE="${THIRAMAI_COMPOSE_FILE:-docker-compose.production.yml}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: ${ENV_FILE} (copy from .env.production.example)" >&2
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "error: compose file not found: ${COMPOSE_FILE}" >&2
  exit 1
fi

# Export all variables from env file for Python, Alembic, and curl defaults
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

PY="${PYTHON:-}"
if [[ -z "$PY" && -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
fi
if [[ -z "$PY" ]]; then
  PY="python3"
fi

AL="${ALEMBIC:-}"
if [[ -z "$AL" && -x "${ROOT}/.venv/bin/alembic" ]]; then
  AL="${ROOT}/.venv/bin/alembic"
fi
if [[ -z "$AL" ]]; then
  AL="alembic"
fi

WEB_PORT="${WEB_PORT:-8000}"
READY_URL="http://127.0.0.1:${WEB_PORT}/health/ready"
HEALTH_RETRIES="${THIRAMAI_HEALTH_RETRIES:-90}"
HEALTH_SLEEP_SEC="${THIRAMAI_HEALTH_SLEEP_SEC:-2}"

if [[ -n "${THIRAMAI_SKIP_GO_LIVE_CHECKLIST:-}" ]]; then
  echo "==> [1/4] Go-live checklist (skipped: THIRAMAI_SKIP_GO_LIVE_CHECKLIST is set)"
else
  echo "==> [1/4] Go-live checklist (scripts/go_live_checklist.py)"
  "$PY" scripts/go_live_checklist.py
fi

echo "==> [2/4] Alembic upgrade head (Phase 8 schema)"
"$AL" upgrade head

echo "==> [3/4] Docker Compose up --build (${COMPOSE_FILE})"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

echo "==> [4/4] Readiness probe: GET ${READY_URL}"
ok=0
for ((i = 1; i <= HEALTH_RETRIES; i++)); do
  if curl -sfS "$READY_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep "$HEALTH_SLEEP_SEC"
done

if [[ "$ok" -ne 1 ]]; then
  echo "error: /health/ready did not succeed within $((HEALTH_RETRIES * HEALTH_SLEEP_SEC))s" >&2
  exit 1
fi

echo "Deployment Successful"
if command -v logger >/dev/null 2>&1; then
  logger -t thiramai "THIRAMAI GENESIS: Deployment Successful (${READY_URL})" || true
fi
