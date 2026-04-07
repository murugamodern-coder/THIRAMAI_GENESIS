#!/usr/bin/env bash
# Follow Docker Compose logs for THIRAMAI (web + db; worker if present).
#
# Usage:
#   ./scripts/tail_compose_logs.sh
#   COMPOSE_FILE=docker-compose.yml ENV_FILE=.env ./scripts/tail_compose_logs.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod-slim.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE (copy .env.production.example → .env.production)" >&2
  exit 1
fi

exec docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs -f web db
