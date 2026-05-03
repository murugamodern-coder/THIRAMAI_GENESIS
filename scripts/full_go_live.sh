#!/usr/bin/env bash
# One-command production bring-up: light pre-check → go_live → verify_live_system
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "╔════════════════════════════════════════════════╗"
echo "║  THIRAMAI FULL GO-LIVE (ONE COMMAND)           ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() { echo -e "\n${BLUE}▶ $1${NC}\n"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }

# Match scripts/go_live.sh base URL resolution for post-verify
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

print_step "Step 1: Checking environment file"
if [[ ! -f .env.production ]]; then
  print_error ".env.production not found!"
  echo ""
  if [[ -f .env.production.example ]]; then
    echo "Creating from template..."
    cp .env.production.example .env.production
  fi
  echo ""
  print_error "IMPORTANT: Edit .env.production with your secrets (DATABASE_URL, SECRET_KEY, POSTGRES_PASSWORD, …)."
  echo "Then run this script again."
  exit 1
fi
print_success "Environment file exists"

print_step "Step 2: Running pre-deployment checks (fast path: skip security & coverage)"
if python scripts/pre_deployment_check.py --skip-security --skip-coverage; then
  print_success "Pre-deployment checks passed"
else
  print_error "Pre-deployment checks failed"
  exit 1
fi

print_step "Step 3: Deploying (full pre-deploy + compose inside go_live.sh)"
export GO_LIVE_CONFIRM="${GO_LIVE_CONFIRM:-yes}"
bash scripts/go_live.sh

print_step "Step 4: Waiting for stability"
echo "Waiting 10 seconds..."
sleep 10

print_step "Step 5: Live system verification"
VERIFY_FLAGS=(--url "$BASE_URL" --skip-tls-verify --env-file .env.production)
if [[ "${THIRAMAI_LIVE_VERIFY_RELAX_DB:-}" == "1" ]]; then
  VERIFY_FLAGS+=(--relax-db)
fi
if [[ "${THIRAMAI_LIVE_VERIFY_SKIP_DOCKER:-}" == "1" ]]; then
  VERIFY_FLAGS+=(--skip-docker)
fi
if python scripts/verify_live_system.py "${VERIFY_FLAGS[@]}"; then
  print_success "Live verification passed"
else
  print_error "Live verification failed"
  echo ""
  echo "Check logs:"
  echo "  docker compose -f docker-compose.production.yml --env-file .env.production logs web"
  exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  🎉🎉🎉 THIRAMAI IS LIVE! 🎉🎉🎉              ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "API base: ${BASE_URL}"
echo ""
echo "📊 Monitor:"
echo "   Health:  ${BASE_URL}/health/ready"
echo "   Metrics: ${BASE_URL}/metrics"
echo "   Quality: ${BASE_URL}/monitoring/ai-quality"
echo ""
echo "📝 Logs:"
echo "   docker compose -f docker-compose.production.yml --env-file .env.production logs -f web"
echo ""
print_success "Deployment complete! 🚀"
