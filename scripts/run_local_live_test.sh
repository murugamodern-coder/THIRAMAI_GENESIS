#!/usr/bin/env bash
# Local live test: deploy (if needed), hit health/auth/decision/metrics, capture log.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.production.yml --env-file .env.production)

echo "╔════════════════════════════════════════════════╗"
echo "║  THIRAMAI LOCAL LIVE TEST                      ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

OUTPUT_FILE="${OUTPUT_FILE:-local_live_test_results.txt}"
SCRATCH="${ROOT_DIR}/.cache/local_live_test"
mkdir -p "$SCRATCH"
rm -f "$OUTPUT_FILE"

pretty_json() {
  local f="$1"
  if [[ ! -s "$f" ]]; then
    echo "(empty)"
    return 0
  fi
  if command -v jq >/dev/null 2>&1; then
    jq '.' "$f" 2>/dev/null || cat "$f"
  else
    python -m json.tool "$f" 2>/dev/null || cat "$f"
  fi
}

log() {
  echo "$1" | tee -a "$OUTPUT_FILE"
}

log "=========================================="
log "THIRAMAI LOCAL LIVE TEST RESULTS"
log "Date: $(date -u 2>/dev/null || date)"
log "=========================================="
log ""

# Step 1: Environment check
log "STEP 1: ENVIRONMENT CHECK"
log "===================="

if [[ -f .env.production ]]; then
  log "✅ .env.production exists"
  log ""
  log "Critical Settings (subset; secrets not shown):"
  grep -E "^(THIRAMAI_DECISION_AB_TEST|DECISION_AB_TEST|POOL_SIZE|THIRAMAI_DB_POOL_SIZE|MAX_OVERFLOW|THIRAMAI_DB_MAX_OVERFLOW|POLICY_ENGINE_PCT|THIRAMAI_POLICY_ENGINE_PCT|WEB_PORT)=" .env.production 2>/dev/null | while read -r line || [[ -n "$line" ]]; do
    log "  $line"
  done || true
else
  log "❌ .env.production missing"
  if [[ -f .env.production.example ]]; then
    log "Creating from template..."
    cp .env.production.example .env.production
  fi
  log "⚠️  Edit .env.production with your secrets before running again"
  exit 1
fi

log ""

# Step 2: Docker services
log "STEP 2: DOCKER SERVICES CHECK"
log "===================="

if command -v docker >/dev/null 2>&1 && "${COMPOSE[@]}" ps --format json >/dev/null 2>&1; then
  log "✅ Docker compose available"
  log ""
  log "Service Status:"
  "${COMPOSE[@]}" ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}" 2>&1 | tee -a "$OUTPUT_FILE"
else
  log "⚠️  Docker compose not running or not available"
fi

log ""

# Step 3: Pre-deployment checks
log "STEP 3: PRE-DEPLOYMENT CHECKS"
log "===================="

if python scripts/pre_deployment_check.py --skip-security --skip-coverage 2>&1 | tee -a "$OUTPUT_FILE"; then
  log "✅ Pre-deployment checks passed"
else
  log "❌ Pre-deployment checks failed"
fi

log ""

# Step 4: Start services (if not running)
log "STEP 4: SERVICE DEPLOYMENT"
log "===================="

log "Ensuring services are running..."
set +e
# Default: build if needed (image is thiramai-app:${DEPLOY_TAG:-latest}). Set THIRAMAI_LIVE_TEST_SKIP_DOCKER_BUILD=1 to run `up -d` only (requires image already present).
if [[ "${THIRAMAI_LIVE_TEST_SKIP_DOCKER_BUILD:-0}" == "1" ]]; then
  "${COMPOSE[@]}" up -d 2>&1 | tee -a "$OUTPUT_FILE"
else
  "${COMPOSE[@]}" up -d --build 2>&1 | tee -a "$OUTPUT_FILE"
fi
UP_STAT="${PIPESTATUS[0]}"
set -e
if [[ "$UP_STAT" -ne 0 ]]; then
  log "⚠️  docker compose up exited non-zero ($UP_STAT) — continuing for diagnostics"
fi

log ""
log "Waiting 30 seconds for services to start..."
sleep 30

log ""

# Resolve base URL
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

# Prefer compose mapping when URL not explicitly overridden (handles WEB_PORT drift).
if [[ -z "${THIRAMAI_GO_LIVE_BASE_URL:-}" ]]; then
  PUB_LINE="$("${COMPOSE[@]}" port web 8000 2>/dev/null | tail -1 || true)"
  if [[ -n "${PUB_LINE}" ]]; then
    PUB_HOST="${PUB_LINE%:*}"
    PUB_PORT="${PUB_LINE##*:}"
    BASE_URL="http://${PUB_HOST}:${PUB_PORT}"
    log "Resolved base URL from compose: ${BASE_URL}"
    log ""
  fi
fi

# Step 5: Health checks
log "STEP 5: HEALTH CHECKS"
log "===================="

log "Base URL: $BASE_URL"
log ""

log "Health - Live:"
CODE="$(curl -sS -o "$SCRATCH/health_live.json" -w "%{http_code}" "${BASE_URL}/health/live" || true)"
if [[ "$CODE" == "200" ]]; then
  log "✅ Live endpoint HTTP 200"
  pretty_json "$SCRATCH/health_live.json" | tee -a "$OUTPUT_FILE"
else
  log "❌ Live endpoint failed (HTTP ${CODE:-error})"
  cat "$SCRATCH/health_live.json" 2>/dev/null | tee -a "$OUTPUT_FILE" || true
fi
log ""

log "Health - Ready:"
CODE="$(curl -sS -o "$SCRATCH/health_ready.json" -w "%{http_code}" "${BASE_URL}/health/ready" || true)"
if [[ "$CODE" == "200" ]]; then
  log "✅ Ready endpoint HTTP 200"
  pretty_json "$SCRATCH/health_ready.json" | tee -a "$OUTPUT_FILE"
else
  log "❌ Ready endpoint failed (HTTP ${CODE:-error})"
  pretty_json "$SCRATCH/health_ready.json" | tee -a "$OUTPUT_FILE"
fi
log ""

log "Health - System:"
CODE="$(curl -sS -o "$SCRATCH/health_system.json" -w "%{http_code}" "${BASE_URL}/health/system" || true)"
if [[ "$CODE" == "200" ]]; then
  log "✅ System endpoint HTTP 200"
  pretty_json "$SCRATCH/health_system.json" | tee -a "$OUTPUT_FILE"
else
  log "❌ System endpoint failed (HTTP ${CODE:-error})"
  pretty_json "$SCRATCH/health_system.json" | tee -a "$OUTPUT_FILE"
fi
log ""

# Step 6: PolicyEngine status
log "STEP 6: POLICYENGINE STATUS"
log "===================="

if [[ -s "$SCRATCH/health_ready.json" ]]; then
  if command -v jq >/dev/null 2>&1; then
    PE_STATUS="$(jq -r '.checks.policy_engine.status // "unknown"' "$SCRATCH/health_ready.json")"
    CB_STATE="$(jq -r '.checks.policy_engine.circuit_breaker.state // "unknown"' "$SCRATCH/health_ready.json")"
  else
    PE_STATUS="$(python -c "import json,sys; d=json.load(open(sys.argv[1])); print(((d.get('checks') or {}).get('policy_engine') or {}).get('status') or 'unknown')" "$SCRATCH/health_ready.json")"
    CB_STATE="$(python -c "import json,sys; d=json.load(open(sys.argv[1])); print(((d.get('checks') or {}).get('policy_engine') or {}).get('circuit_breaker') or {}).get('state') or 'unknown')" "$SCRATCH/health_ready.json")"
  fi
  log "PolicyEngine Status: $PE_STATUS"
  log "Circuit Breaker State: $CB_STATE"
  if [[ "$PE_STATUS" == "healthy" || "$PE_STATUS" == "degraded" ]]; then
    log "✅ PolicyEngine operational"
  else
    log "❌ PolicyEngine not healthy"
  fi
else
  log "⚠️  Cannot determine PolicyEngine status (no ready JSON)"
fi

log ""

# Step 7: Authentication test
log "STEP 7: AUTHENTICATION TEST"
log "===================="

AUTH_USER="${THIRAMAI_LIVE_VERIFY_USER:-admin_king}"
AUTH_PASS="${THIRAMAI_LIVE_VERIFY_PASSWORD:-thiramai_2026}"

log "Testing login with user: $AUTH_USER"

TOKEN=""
CODE="$(curl -sS -o "$SCRATCH/auth_response.json" -w "%{http_code}" -X POST "${BASE_URL}/auth/login" \
  -d "username=${AUTH_USER}&password=${AUTH_PASS}" || true)"
if [[ "$CODE" == "200" ]]; then
  if command -v jq >/dev/null 2>&1; then
    TOKEN="$(jq -r '.access_token // ""' "$SCRATCH/auth_response.json")"
  else
    TOKEN="$(python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('access_token') or '')" "$SCRATCH/auth_response.json")"
  fi
  if [[ -n "$TOKEN" && "$TOKEN" != "null" ]]; then
    log "✅ Authentication successful"
    log "Token obtained (length: ${#TOKEN} chars)"
  else
    log "❌ No token in response"
    pretty_json "$SCRATCH/auth_response.json" | tee -a "$OUTPUT_FILE"
  fi
else
  log "❌ Authentication failed (HTTP ${CODE:-error})"
  pretty_json "$SCRATCH/auth_response.json" | tee -a "$OUTPUT_FILE"
fi

log ""

# Step 8: Decision API test
log "STEP 8: DECISION API TEST"
log "===================="

if [[ -n "$TOKEN" ]]; then
  log "Testing decision API..."
  CODE="$(curl -sS -o "$SCRATCH/decision_response.json" -w "%{http_code}" -X POST "${BASE_URL}/chat/decision" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message":"Should I invest in gold now?"}' || true)"
  if [[ "$CODE" == "200" ]]; then
    log "✅ Decision API call successful"
    log ""
    log "Response:"
    pretty_json "$SCRATCH/decision_response.json" | tee -a "$OUTPUT_FILE"
    if command -v jq >/dev/null 2>&1; then
      BRAIN_SOURCE="$(jq -r '.decision.data.decision_brain_source // "unknown"' "$SCRATCH/decision_response.json")"
    else
      BRAIN_SOURCE="$(python -c "import json,sys; d=json.load(open(sys.argv[1])); r=d.get('decision') or {}; print((r.get('data') or {}).get('decision_brain_source') or 'unknown')" "$SCRATCH/decision_response.json")"
    fi
    log ""
    log "AI Brain Source: $BRAIN_SOURCE"
    if [[ "$BRAIN_SOURCE" == "policy_engine" ]]; then
      log "✅✅✅ USING POLICYENGINE (AI BRAIN ACTIVE!) ✅✅✅"
    elif [[ "$BRAIN_SOURCE" == "safe_fallback" ]]; then
      log "⚠️  Using safe fallback (degraded mode)"
    else
      log "❌ Unexpected brain source: $BRAIN_SOURCE"
    fi
  else
    log "❌ Decision API call failed (HTTP ${CODE:-error})"
    pretty_json "$SCRATCH/decision_response.json" | tee -a "$OUTPUT_FILE"
  fi
else
  log "⚠️  Skipping (no auth token)"
fi

log ""

# Step 9: Quality tracking
log "STEP 9: AI QUALITY TRACKING"
log "===================="

if [[ -n "$TOKEN" ]]; then
  log "Checking quality tracking endpoint..."
  CODE="$(curl -sS -o "$SCRATCH/quality_response.json" -w "%{http_code}" -X GET "${BASE_URL}/monitoring/ai-quality" \
    -H "Authorization: Bearer $TOKEN" || true)"
  if [[ "$CODE" == "200" ]]; then
    log "✅ Quality tracking accessible"
    pretty_json "$SCRATCH/quality_response.json" | tee -a "$OUTPUT_FILE"
  else
    log "❌ Quality tracking failed (HTTP ${CODE:-error})"
    pretty_json "$SCRATCH/quality_response.json" | tee -a "$OUTPUT_FILE"
  fi
else
  log "⚠️  Skipping (no auth token)"
fi

log ""

# Step 10: Metrics
log "STEP 10: METRICS CHECK"
log "===================="

log "Checking Prometheus metrics..."
if curl -f -sS "${BASE_URL}/metrics" -o "$SCRATCH/metrics.txt"; then
  log "✅ Metrics endpoint accessible"
  log ""
  log "Key Metrics:"
  grep -E "thiramai_policy_engine_circuit_state|thiramai_safe_fallback_decisions_total|thiramai_requests_total" "$SCRATCH/metrics.txt" 2>/dev/null | head -15 | tee -a "$OUTPUT_FILE" || log "(no matches)"
else
  log "❌ Metrics endpoint failed"
fi

log ""

# Step 11: Docker logs sample
log "STEP 11: RECENT LOGS SAMPLE"
log "===================="

log "Last 30 lines from web service:"
"${COMPOSE[@]}" logs --tail 30 web 2>&1 | tee -a "$OUTPUT_FILE" || log "(web service logs unavailable)"

log ""

# Step 12: Full verification
log "STEP 12: COMPREHENSIVE VERIFICATION"
log "===================="

log "Running verify_live_system.py..."
log ""

set +e
python scripts/verify_live_system.py --skip-tls-verify --url "$BASE_URL" --env-file .env.production 2>&1 | tee -a "$OUTPUT_FILE"
VS="$?"
set -e
if [[ "$VS" -eq 0 ]]; then
  log ""
  log "✅✅✅ FULL VERIFICATION PASSED ✅✅✅"
else
  log ""
  log "⚠️  Some verification checks failed (verify_live_system exit $VS — see details above)"
fi

log ""

# Final summary
log "=========================================="
log "TEST COMPLETE"
log "=========================================="
log ""
log "Results saved to: $OUTPUT_FILE"
log ""
log "Quick verification commands:"
log "  Health:  curl ${BASE_URL}/health/ready"
log "  Metrics: curl ${BASE_URL}/metrics | grep policy_engine"
log "  docker compose -f docker-compose.production.yml --env-file .env.production logs -f web"
log ""

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  TEST COMPLETE - Check $OUTPUT_FILE           ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "Share $OUTPUT_FILE for analysis!"
