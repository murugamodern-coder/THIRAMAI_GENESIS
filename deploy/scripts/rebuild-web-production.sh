#!/usr/bin/env bash
# Rebuild the **web** (FastAPI) image from the current clone and force a new container.
# Run on the production host from the repo root (e.g. /root/thiramai-app) with .env.production present.
#
#   chmod +x deploy/scripts/rebuild-web-production.sh
#   ./deploy/scripts/rebuild-web-production.sh
#
# This uses `docker compose` so the new `build:` on the `web` service in docker-compose.production.yml
# is actually executed (previously `web` was image-only and `compose build web` was a no-op).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f docker-compose.production.yml"
if [[ -f .env.production ]]; then
  COMPOSE="$COMPOSE --env-file .env.production"
fi

echo "==> Building web from source (no cache)…"
$COMPOSE build --no-cache web

echo "==> Recreating web container…"
$COMPOSE up -d --force-recreate web

echo "==> Done. Verify routes:"
echo "    curl -sfS '${PUBLIC_URL:-https://app.thiramai.co.in}/openapi.json' | jq 'has(\"paths\") and (.paths | has(\"/ai/goal\"))'"
echo "    curl -sfS '${PUBLIC_URL:-https://app.thiramai.co.in}/openapi.json' | grep '\"\\/ai\\/goal\"'"
