#!/usr/bin/env bash
# THIRAMAI — lightweight production liveness checks (run on the cloud server).
#
# Usage:
#   export THIRAMAI_BASE_URL=https://api.yourdomain.com   # optional; default http://127.0.0.1:8000
#   export COMPOSE_FILE=docker-compose.production.yml
#   export ENV_FILE=.env.production
#   bash scripts/production_health_probe.sh
#
# Exit 0 only if API responds and (when compose files exist) Redis PING + Postgres ready succeed.

set -euo pipefail

BASE_URL="${THIRAMAI_BASE_URL:-http://127.0.0.1:8000}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
# Space-separated compose *service* names (production default). Dev full stack: "web worker-jobs worker"
CHECK_SERVICES="${THIRAMAI_COMPOSE_SERVICES:-web worker-jobs worker-alerts}"

echo "=== THIRAMAI production health probe ==="
echo "API: ${BASE_URL}"

fail=0

if ! curl -fsS -m 15 -H 'Accept: application/json' "${BASE_URL}/" >/dev/null; then
  echo "[FAIL] API GET / (JSON) did not return success"
  fail=1
else
  echo "[OK]   API GET / (JSON)"
fi

compose() {
  docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" "$@"
}

if [[ -f "${COMPOSE_FILE}" && -f "${ENV_FILE}" ]]; then
  if ! compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "[FAIL] Redis PING via compose exec redis"
    fail=1
  else
    echo "[OK]   Redis PING"
  fi

  PG_USER="${POSTGRES_USER:-thiramai}"
  PG_DB="${POSTGRES_DB:-thiramai}"
  if ! compose exec -T db pg_isready -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
    echo "[FAIL] Postgres pg_isready (db service)"
    fail=1
  else
    echo "[OK]   Postgres pg_isready"
  fi

  echo "--- compose ps (name / state) ---"
  compose ps --format 'table {{.Name}}\t{{.Service}}\t{{.Status}}' || true

  # Require core services to appear "Up" or "running" in status text
  ps_out="$(compose ps --format '{{.Service}} {{.Status}}' 2>/dev/null || true)"
  for svc in ${CHECK_SERVICES}; do
    if echo "${ps_out}" | grep "^${svc} " | grep -qiE 'up|running'; then
      echo "[OK]   service ${svc} appears running"
    else
      echo "[FAIL] service ${svc} not running (check: docker compose -f ${COMPOSE_FILE} logs ${svc})"
      fail=1
    fi
  done
else
  echo "[SKIP] ${COMPOSE_FILE} or ${ENV_FILE} missing — Redis/DB/worker checks skipped"
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "=== Result: UNHEALTHY ==="
  exit 1
fi
echo "=== Result: OK ==="
exit 0
