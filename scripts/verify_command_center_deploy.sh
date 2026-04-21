#!/usr/bin/env bash
# Run on the production host (same cwd / env as deploy) to audit what the web
# container actually serves for Command Center / #/personal.
#
# Usage:
#   export THIRAMAI_ENV_FILE=/root/thiramai-app/.env.production
#   export THIRAMAI_COMPOSE_FILE=docker-compose.production.yml
#   ./scripts/verify_command_center_deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${THIRAMAI_ENV_FILE:-.env.production}"
COMPOSE="${THIRAMAI_COMPOSE_FILE:-docker-compose.production.yml}"
DC=(docker compose -f "$COMPOSE" --env-file "$ENV_FILE")

echo "=== STEP 1a: index.html inside web container (must reference cc-app-<hash>.js only) ==="
"${DC[@]}" exec -T web cat /app/static/command_center/index.html

echo ""
echo "=== STEP 1a2: legacy cc-app.js must not exist ==="
"${DC[@]}" exec -T web sh -c 'test ! -f /app/static/command_center/cc-app.js && echo OK || echo FAIL'

echo ""
echo "=== STEP 1b: script/link tags (cc-app / cc-index) ==="
"${DC[@]}" exec -T web grep -oE 'cc-(app|index)[^"]*' /app/static/command_center/index.html || true

echo ""
echo "=== STEP 1c: hashed cc-app (legacy cc-app.js must be absent) ==="
"${DC[@]}" exec -T web sh -c 'if test -f /app/static/command_center/cc-app.js; then echo "FAIL: legacy cc-app.js present"; else echo "OK: no legacy cc-app.js"; fi'
"${DC[@]}" exec -T web sh -c 'ls -1 /app/static/command_center/cc-app-*.js 2>/dev/null | head -5 || echo "(no cc-app-*.js)"'

echo ""
echo "=== STEP 1d: optional string check in hashed bundle (Add Habit count; 0 may be OK) ==="
"${DC[@]}" exec -T web sh -c 'for f in /app/static/command_center/cc-app-*.js; do test -f "$f" && grep -c "Add Habit" "$f" && break; done' || true

echo ""
echo "=== Local repo (run from dev machine): no legacy cc-app.js; hashed cc-app-*.js only ==="
if [[ -f static/command_center/cc-app.js ]]; then
  echo "FAIL: static/command_center/cc-app.js exists (remove before deploy)"
else
  echo "OK: no legacy cc-app.js"
fi
shopt -s nullglob
_local_cc=(static/command_center/cc-app-*.js)
if ((${#_local_cc[@]})); then
  echo "Hashed bundles: ${_local_cc[*]}"
else
  echo "(no local static/command_center/cc-app-*.js — run npm run build in web/command_center)"
fi
shopt -u nullglob
