#!/usr/bin/env bash
# THIRAMAI production E2E smoke checks (no secrets baked in).
# Usage:
#   export BASE_URL=https://app.thiramai.co.in
#   ./e2e-validate-production.sh
# With authenticated goal test:
#   export JWT_ACCESS_TOKEN='eyJ...'
#   ./e2e-validate-production.sh
set -euo pipefail

BASE_URL="${BASE_URL:-https://app.thiramai.co.in}"
RED='\033[0;31m'
GRN='\033[0;32m'
NC='\033[0m'

fail() { echo -e "${RED}FAIL:${NC} $*"; exit 1; }
ok() { echo -e "${GRN}OK:${NC} $*"; }

echo "=== Step 2: Health ==="
code_live="$(curl -sS -o /tmp/th_live.json -w "%{http_code}" "${BASE_URL}/health/live")"
[[ "$code_live" == "200" ]] || fail "/health/live HTTP $code_live"
grep -q '"status"' /tmp/th_live.json || fail "/health/live not JSON"
ok "/health/live -> 200"

code_ready="$(curl -sS -o /tmp/th_ready.json -w "%{http_code}" "${BASE_URL}/health/ready")"
[[ "$code_ready" == "200" ]] || fail "/health/ready HTTP $code_ready"
grep -q '"status"' /tmp/th_ready.json || fail "/health/ready not JSON"
ok "/health/ready -> 200"

echo "=== Step 3: Frontend (/) ==="
code_root="$(curl -sS -L -o /dev/null -w "%{http_code}" "${BASE_URL}/")"
[[ "$code_root" == "200" ]] || fail "/ HTTP $code_root"
ok "GET / -> $code_root"

echo "=== OpenAPI: autonomous goals registered? ==="
curl -sfS "${BASE_URL}/openapi.json" -o /tmp/th_openapi.json
HAS_GOAL_API=0
if command -v jq >/dev/null 2>&1; then
  if jq -e '.paths["/ai/goal"].post' /tmp/th_openapi.json >/dev/null 2>&1; then
    ok "OpenAPI defines POST /ai/goal — goal API is deployed"
    HAS_GOAL_API=1
  else
    echo -e "${RED}WARN:${NC} POST /ai/goal missing from OpenAPI."
    echo "Redeploy the FastAPI image built from current THIRAMAI Genesis (see api/routes/registry.py)."
  fi
else
  echo "jq not installed — cannot verify /ai/goal in OpenAPI; skipping authenticated goal POST."
  HAS_GOAL_API=0
fi

if [[ "${JWT_ACCESS_TOKEN:-}" != "" && "$HAS_GOAL_API" == "1" ]]; then
  echo "=== Step 4: POST /ai/goal (authenticated) ==="
  resp="$(curl -sS -w "\n%{http_code}" -X POST "${BASE_URL}/ai/goal" \
    -H "Authorization: Bearer ${JWT_ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"goal":"Test system health check - e2e validate"}')"
  body="$(echo "$resp" | head -n -1)"
  code="$(echo "$resp" | tail -n 1)"
  [[ "$code" == "200" || "$code" == "409" ]] || fail "POST /ai/goal HTTP $code body=$body"
  ok "POST /ai/goal -> $code"
elif [[ "${JWT_ACCESS_TOKEN:-}" == "" ]]; then
  echo "JWT_ACCESS_TOKEN unset — skipping authenticated goal submit."
else
  echo "Skipping POST /ai/goal (route missing from OpenAPI)."
fi

echo "=== Done ==="
