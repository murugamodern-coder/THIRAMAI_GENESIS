#!/usr/bin/env bash
# THIRAMAI: tear down production compose stack, remove DB/Redis volumes, bring stack up, migrate, seed.
# WARNING: destroys all data in thiramai_pgdata and thiramai_redis.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.production.yml --env-file .env.production)

echo "================================================================"
echo "  THIRAMAI COMPLETE RESET & INITIALIZATION"
echo "================================================================"
echo ""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() { echo -e "\n${BLUE}>> $1${NC}\n"; }
print_success() { echo -e "${GREEN}OK $1${NC}"; }
print_error() { echo -e "${RED}FAIL $1${NC}"; }
print_warn() { echo -e "${YELLOW}WARN $1${NC}"; }

# Postgres identity (must match .env.production / compose defaults)
PG_USER="${POSTGRES_USER:-thiramai}"
PG_DB="${POSTGRES_DB:-thiramai}"
if [[ -f .env.production ]]; then
  _line="$(grep -E '^POSTGRES_USER=' .env.production 2>/dev/null | tail -1 || true)"
  [[ -n "${_line}" ]] && PG_USER="${_line#POSTGRES_USER=}" && PG_USER="${PG_USER%%[$'\r']}"
  _line="$(grep -E '^POSTGRES_DB=' .env.production 2>/dev/null | tail -1 || true)"
  [[ -n "${_line}" ]] && PG_DB="${_line#POSTGRES_DB=}" && PG_DB="${PG_DB%%[$'\r']}"
fi

print_warn "This runs: docker compose down -v (deletes DB + Redis volumes and all data)."
print_warn "Consider: bash scripts/backup_before_reset.sh (if stack is up and you need a dump)."
echo ""
read -r -p "Type \"yes\" to continue: " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
  echo "Cancelled."
  exit 0
fi

print_step "Step 1: Stop services and remove volumes"
"${COMPOSE[@]}" down -v
print_success "Compose down -v complete"

print_step "Step 2: Verify .env.production"
if [[ ! -f .env.production ]]; then
  print_error ".env.production not found"
  exit 1
fi
if ! grep -qE '^POSTGRES_PASSWORD=' .env.production; then
  print_error "POSTGRES_PASSWORD missing in .env.production"
  exit 1
fi
if ! grep -qE '^DATABASE_URL=' .env.production; then
  print_error "DATABASE_URL missing in .env.production"
  exit 1
fi
# DATABASE_URL password should match POSTGRES_PASSWORD (user responsibility)
print_success ".env.production has POSTGRES_PASSWORD and DATABASE_URL"

print_step "Step 3: Build and start stack"
"${COMPOSE[@]}" up -d --build
print_success "Stack started"

print_step "Step 4: Wait for Postgres (pg_isready)"
sleep 5
ready=0
for i in $(seq 1 24); do
  if "${COMPOSE[@]}" exec -T db pg_isready -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
    ready=1
    break
  fi
  echo "  waiting db ... ${i}/24"
  sleep 5
done
if [[ "${ready}" -ne 1 ]]; then
  print_error "Postgres not ready. Logs: ${COMPOSE[*]} logs db"
  exit 1
fi
print_success "Postgres is ready"

print_step "Step 5: Wait for web /health/live"
WEB_PORT="8000"
_line="$(grep -E '^WEB_PORT=' .env.production 2>/dev/null | tail -1 || true)"
[[ -n "${_line}" ]] && WEB_PORT="${_line#WEB_PORT=}" && WEB_PORT="${WEB_PORT%%[$'\r']}"
BASE_URL="http://127.0.0.1:${WEB_PORT}"
_pub="$("${COMPOSE[@]}" port web 8000 2>/dev/null | tail -1 || true)"
if [[ -n "${_pub}" ]]; then
  _host="${_pub%:*}"
  _port="${_pub##*:}"
  BASE_URL="http://${_host}:${_port}"
fi
live_ok=0
for i in $(seq 1 36); do
  if curl -fsS "${BASE_URL}/health/live" >/dev/null 2>&1; then
    live_ok=1
    break
  fi
  echo "  waiting web live ... ${i}/36 (${BASE_URL})"
  sleep 5
done
if [[ "${live_ok}" -ne 1 ]]; then
  print_warn "Web /health/live not OK yet at ${BASE_URL} — continuing (check logs)"
else
  print_success "Web live probe OK (${BASE_URL})"
fi

print_step "Step 6: Alembic upgrade head (in web)"
if "${COMPOSE[@]}" exec -T web alembic upgrade head; then
  print_success "Migrations applied"
else
  print_error "Migrations failed — ${COMPOSE[*]} logs web"
  exit 1
fi

print_step "Step 7: Seed admin_king"
if "${COMPOSE[@]}" exec -T web python scripts/seed_admin_king.py; then
  print_success "Admin seeded"
else
  print_error "seed_admin_king failed"
  exit 1
fi

print_step "Step 8: Verify DB from web container"
DB_CHECK="$("${COMPOSE[@]}" exec -T web python -c "
from sqlalchemy import text
from core.database import get_session_factory
f = get_session_factory()
if f is None:
    print('ERROR: no session factory')
    raise SystemExit(2)
with f() as s:
    v = s.execute(text('SELECT 1')).scalar()
print('OK' if v == 1 else 'FAIL')
" 2>&1)" || true
if echo "${DB_CHECK}" | grep -q "OK"; then
  print_success "Web -> DB SELECT 1 OK"
else
  print_error "DB check: ${DB_CHECK}"
  exit 1
fi

print_step "Step 9: Auth diagnostics (in web, HTTP against container :8000)"
if "${COMPOSE[@]}" exec -T -e THIRAMAI_DIAGNOSE_AUTH_URL=http://127.0.0.1:8000 web python scripts/diagnose_auth.py; then
  print_success "Auth diagnostics passed"
else
  print_warn "Auth diagnostics reported issues — review output above"
fi

print_step "Step 10: Health endpoints (host)"
if curl -fsS "${BASE_URL}/health/live" >/dev/null 2>&1; then
  print_success "GET ${BASE_URL}/health/live"
else
  print_warn "GET ${BASE_URL}/health/live failed"
fi
if curl -fsS "${BASE_URL}/health/ready" >/dev/null 2>&1; then
  print_success "GET ${BASE_URL}/health/ready"
else
  print_warn "GET ${BASE_URL}/health/ready failed (migrations/AI keys/etc.)"
fi

echo ""
echo "================================================================"
echo "  RESET & INITIALIZATION FINISHED"
echo "================================================================"
echo ""
echo "UI login:   ${BASE_URL}/static/command_center/index.html#/login"
echo "API docs:   ${BASE_URL}/docs"
echo ""
echo "Username:   admin_king   (or email admin@thiramai.local)"
echo "Password:   thiramai_2026"
echo ""
echo "HTTP login test:"
echo "  curl -sS -X POST \"${BASE_URL}/auth/login\" -d \"username=admin_king\" -d \"password=thiramai_2026\""
echo ""
print_success "Done."
