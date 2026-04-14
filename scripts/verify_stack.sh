#!/usr/bin/env bash
# THIRAMAI — verify Docker stack, Alembic, and /health/ready (one command at a time).
# Usage: bash scripts/verify_stack.sh
# From repo root; requires .env.production and docker-compose.production.yml

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${THIRAMAI_ENV_FILE:-.env.production}"
COMPOSE_FILE="${THIRAMAI_COMPOSE_FILE:-docker-compose.production.yml}"
WEB_PORT="${WEB_PORT:-8000}"
EXEC_TIMEOUT="${THIRAMAI_DOCKER_EXEC_TIMEOUT:-120}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: missing ${ENV_FILE} (copy from .env.production.example)" >&2
  exit 1
fi

echo ""
echo "=== docker compose ps ==="
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

echo ""
echo "=== alembic current (exec -T, timeout ${EXEC_TIMEOUT}s) ==="
if command -v timeout >/dev/null 2>&1; then
  timeout "$EXEC_TIMEOUT" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T web alembic current \
    || echo "note: exec failed or timed out — run: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs web --tail 200"
else
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T web alembic current \
    || echo "note: exec failed — run: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs web --tail 200"
fi

echo ""
echo "=== curl /health/ready ==="
curl -sS -w "\nHTTP %{http_code}\n" --max-time 15 "http://127.0.0.1:${WEB_PORT}/health/ready" || true

echo ""
echo "Done. See docs/OPS_TERMINAL_AND_DOCKER.md"
