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

echo "=== STEP 1a: index.html inside web container ==="
"${DC[@]}" exec -T web cat /app/static/command_center/index.html

echo ""
echo "=== STEP 1b: script/link tags (cc-app / cc-index) ==="
"${DC[@]}" exec -T web grep -oE 'cc-(app|index)[^"]*' /app/static/command_center/index.html || true

echo ""
echo "=== STEP 1c: count 'Add Habit' in cc-app.js (0 = stale or wrong bundle) ==="
"${DC[@]}" exec -T web grep -c "Add Habit" /app/static/command_center/cc-app.js || true

echo ""
echo "=== Local repo (run from dev machine): grep -c Add Habit static/command_center/cc-app.js ==="
if [[ -f static/command_center/cc-app.js ]]; then
  grep -c "Add Habit" static/command_center/cc-app.js || true
else
  echo "(no local static/command_center/cc-app.js)"
fi
