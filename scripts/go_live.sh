#!/usr/bin/env bash
# THIRAMAI GENESIS — local / single-host production bring-up
# Requires: Docker Compose v2, curl, Python 3 (same env as pre_deployment_check).
#
# Optional env:
#   THIRAMAI_GO_LIVE_BASE_URL — full API base (overrides host/port below)
#   THIRAMAI_GO_LIVE_HOST     — default 127.0.0.1
#   THIRAMAI_GO_LIVE_PORT     — default: WEB_PORT from .env.production or 8000
#   GO_LIVE_CONFIRM=yes       — skip interactive confirmation
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "╔════════════════════════════════════════════════╗"
echo "║  THIRAMAI GENESIS - LIVE DEPLOYMENT            ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_step() { echo ""; echo "▶ $1"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }

# Resolve base URL (match docker-compose.production host bind + WEB_PORT)
GO_LIVE_HOST="${THIRAMAI_GO_LIVE_HOST:-127.0.0.1}"
GO_LIVE_PORT="${THIRAMAI_GO_LIVE_PORT:-}"
if [[ -z "$GO_LIVE_PORT" ]] && [[ -f .env.production ]]; then
  line="$(grep -E '^WEB_PORT=' .env.production 2>/dev/null | tail -1 || true)"
  if [[ -n "$line" ]]; then
    GO_LIVE_PORT="${line#WEB_PORT=}"
    GO_LIVE_PORT="${GO_LIVE_PORT%%[$'\r']}"
  fi
fi
GO_LIVE_PORT="${GO_LIVE_PORT:-8000}"

if [[ -n "${THIRAMAI_GO_LIVE_BASE_URL:-}" ]]; then
  BASE_URL="${THIRAMAI_GO_LIVE_BASE_URL%/}"
else
  BASE_URL="http://${GO_LIVE_HOST}:${GO_LIVE_PORT}"
fi

HEALTH_URL="${BASE_URL}/health/ready"

print_step "Step 1: Running pre-deployment verification..."
if python scripts/pre_deployment_check.py; then
  print_success "Pre-deployment checks passed"
else
  print_error "Pre-deployment checks failed"
  echo "Fix issues above before deploying"
  exit 1
fi

print_step "Step 2: Deployment confirmation"
if [[ "${GO_LIVE_CONFIRM:-}" != "yes" ]]; then
  echo ""
  echo "Ready to deploy THIRAMAI to production."
  echo "Using API base: ${BASE_URL}"
  echo "This will:"
  echo "  - Build production Docker images"
  echo "  - Start services with production config"
  echo "  - Run live verification"
  echo ""
  read -r -p "Continue? (yes/no): " CONFIRM
  if [[ "$CONFIRM" != "yes" ]]; then
    print_warning "Deployment cancelled"
    exit 0
  fi
else
  echo "GO_LIVE_CONFIRM=yes — skipping interactive prompt"
fi

print_step "Step 3: Building and starting production services..."
docker compose -f docker-compose.production.yml --env-file .env.production down 2>/dev/null || true
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
print_success "Services started"

print_step "Step 4: Waiting for services to be ready..."
echo "Waiting 30 seconds for startup..."
sleep 30

print_step "Step 5: Verifying health endpoints..."
for i in $(seq 1 10); do
  if curl -f -sS "$HEALTH_URL" > /dev/null; then
    print_success "Health check passed (${HEALTH_URL})"
    break
  fi
  if [[ "$i" -eq 10 ]]; then
    print_error "Health check failed after 10 attempts (${HEALTH_URL})"
    echo "Check logs: docker compose -f docker-compose.production.yml logs"
    exit 1
  fi
  echo "Attempt $i/10 failed, retrying..."
  sleep 5
done

print_step "Step 6: Verifying PolicyEngine status..."
RAW_HEALTH="$(curl -sS "$HEALTH_URL")"
if command -v jq >/dev/null 2>&1; then
  POLICY_STATUS="$(echo "$RAW_HEALTH" | jq -r '.checks.policy_engine.status // empty')"
else
  POLICY_STATUS="$(echo "$RAW_HEALTH" | python -c "import json,sys; d=json.load(sys.stdin); print((d.get('checks') or {}).get('policy_engine') or {}).get('status') or '')")"
fi

if [[ "$POLICY_STATUS" == "healthy" ]]; then
  print_success "PolicyEngine operational"
elif [[ "$POLICY_STATUS" == "degraded" ]]; then
  print_warning "PolicyEngine degraded (circuit breaker / fallback path — see health JSON)"
else
  print_error "PolicyEngine unhealthy or missing (status='${POLICY_STATUS}')"
  exit 1
fi

print_step "Step 7: Running post-deployment verification..."
if python scripts/verify_deployment.py --url "$BASE_URL" --skip-tls-verify; then
  print_success "Deployment verification passed"
else
  print_error "Deployment verification failed"
  exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  🎉 DEPLOYMENT SUCCESSFUL! 🎉                 ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "📊 Next steps:"
echo ""
echo "1. Monitor health:"
echo "   curl ${HEALTH_URL}"
echo ""
echo "2. Test decision API:"
echo "   # Get token first:"
echo "   curl -X POST ${BASE_URL}/auth/login \\"
echo "     -d 'username=admin_king' -d 'password=thiramai_2026'"
echo ""
echo "   # Then make decision:"
echo "   curl -X POST ${BASE_URL}/chat/decision \\"
echo "     -H 'Authorization: Bearer TOKEN' \\"
echo "     -d '{\"message\":\"test\"}'"
echo ""
echo "3. Check AI quality:"
echo "   curl ${BASE_URL}/monitoring/ai-quality \\"
echo "     -H 'Authorization: Bearer TOKEN'"
echo ""
echo "4. View logs:"
echo "   docker compose -f docker-compose.production.yml logs -f"
echo ""
echo "5. Monitor metrics:"
echo "   curl ${BASE_URL}/metrics | grep policy_engine"
echo ""
print_success "THIRAMAI is now LIVE! 🚀"
