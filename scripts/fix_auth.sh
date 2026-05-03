#!/usr/bin/env bash
# One-shot: migrations + seed admin inside web container, then re-run auth diagnostics in-container.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.production.yml --env-file .env.production)

echo "Authentication Quick Fix"
echo "========================"
echo ""

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not on PATH"
  exit 1
fi

ids="$("${COMPOSE[@]}" ps -q web 2>/dev/null || true)"
if [ -z "${ids}" ]; then
  echo "ERROR: web service has no running container. Start the stack first:"
  echo "  ${COMPOSE[*]} up -d"
  exit 1
fi

echo "Step 1: alembic upgrade head (inside web)"
"${COMPOSE[@]}" exec -T web alembic upgrade head

echo ""
echo "Step 2: seed admin_king + org (inside web)"
"${COMPOSE[@]}" exec -T web python scripts/seed_admin_king.py

echo ""
echo "Step 3: diagnose_auth.py (inside web — uses container DATABASE_URL)"
"${COMPOSE[@]}" exec -T web python scripts/diagnose_auth.py

echo ""
echo "Done. Try Command Center login:"
echo "  username: admin_king   (or email admin@thiramai.local)"
echo "  password: thiramai_2026"
echo ""
echo "From the host (optional), if API is published on localhost:"
echo "  THIRAMAI_DIAGNOSE_AUTH_URL=http://127.0.0.1:<WEB_PORT> python scripts/diagnose_auth.py"
