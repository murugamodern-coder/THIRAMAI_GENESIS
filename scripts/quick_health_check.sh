#!/usr/bin/env bash
# Quick HTTP health checks against the production compose web service.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.production.yml --env-file .env.production)

echo "Quick Health Check"
echo "=================="
echo ""

WEB_PORT="${WEB_PORT:-8000}"
if [[ -f .env.production ]]; then
  line="$(grep -E '^WEB_PORT=' .env.production 2>/dev/null | tail -1 || true)"
  if [[ -n "${line:-}" ]]; then
    WEB_PORT="${line#WEB_PORT=}"
    WEB_PORT="${WEB_PORT%%[$'\r']}"
  fi
fi

BASE_URL="${THIRAMAI_GO_LIVE_BASE_URL:-http://127.0.0.1:${WEB_PORT}}"
BASE_URL="${BASE_URL%/}"

if [[ -z "${THIRAMAI_GO_LIVE_BASE_URL:-}" ]]; then
  PUB_LINE="$("${COMPOSE[@]}" port web 8000 2>/dev/null | tail -1 || true)"
  if [[ -n "${PUB_LINE}" ]]; then
    PUB_HOST="${PUB_LINE%:*}"
    PUB_PORT="${PUB_LINE##*:}"
    BASE_URL="http://${PUB_HOST}:${PUB_PORT}"
  fi
fi

echo "Base URL: $BASE_URL"
echo ""

echo -n "Health Live: "
if curl -f -sS "${BASE_URL}/health/live" > /dev/null 2>&1; then
  echo "OK"
else
  echo "FAIL"
  exit 1
fi

READY_FILE="${ROOT_DIR}/.cache/local_live_test/quick_health_ready.json"
mkdir -p "$(dirname "$READY_FILE")"
echo -n "Health Ready: "
CODE="$(curl -sS -o "$READY_FILE" -w "%{http_code}" "${BASE_URL}/health/ready" || true)"
if [[ "$CODE" == "200" ]]; then
  echo "OK"
  PE_STATUS="$(python -c "import json,sys; d=json.load(open(sys.argv[1])); print(((d.get('checks') or {}).get('policy_engine') or {}).get('status') or 'unknown')" "$READY_FILE" 2>/dev/null || echo "unknown")"
  CB_STATE="$(python -c "import json,sys; d=json.load(open(sys.argv[1])); print(((d.get('checks') or {}).get('policy_engine') or {}).get('circuit_breaker') or {}).get('state') or 'unknown')" "$READY_FILE" 2>/dev/null || echo "unknown")"
  echo "  PolicyEngine: $PE_STATUS"
  echo "  Circuit: $CB_STATE"
else
  echo "FAIL (HTTP ${CODE})"
  exit 1
fi

echo ""
echo "System healthy (live + ready)."
