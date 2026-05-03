#!/usr/bin/env bash
# Optional: pg_dump + copy .env.production before destructive reset.
# Run from repo root with stack UP and DB reachable.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.production.yml --env-file .env.production)

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${ROOT_DIR}/backups/pre_reset_${STAMP}"
mkdir -p "${BACKUP_DIR}"

PG_USER="${POSTGRES_USER:-thiramai}"
PG_DB="${POSTGRES_DB:-thiramai}"
if [[ -f .env.production ]]; then
  _line="$(grep -E '^POSTGRES_USER=' .env.production 2>/dev/null | tail -1 || true)"
  [[ -n "${_line}" ]] && PG_USER="${_line#POSTGRES_USER=}" && PG_USER="${PG_USER%%[$'\r']}"
  _line="$(grep -E '^POSTGRES_DB=' .env.production 2>/dev/null | tail -1 || true)"
  [[ -n "${_line}" ]] && PG_DB="${_line#POSTGRES_DB=}" && PG_DB="${PG_DB%%[$'\r']}"
  cp .env.production "${BACKUP_DIR}/.env.production.backup"
  echo "OK: copied .env.production -> ${BACKUP_DIR}/"
fi

echo "Dumping database ${PG_DB} as user ${PG_USER} ..."
if "${COMPOSE[@]}" exec -T db pg_dump -U "${PG_USER}" "${PG_DB}" > "${BACKUP_DIR}/database.sql"; then
  echo "OK: ${BACKUP_DIR}/database.sql ($(wc -c < "${BACKUP_DIR}/database.sql") bytes)"
else
  echo "WARN: pg_dump failed (is the stack up?). Backup dir still has .env if copied."
  exit 1
fi

echo ""
echo "Backup directory: ${BACKUP_DIR}"
echo "Restore example (after db is up, empty DB):"
echo "  cat ${BACKUP_DIR}/database.sql | ${COMPOSE[*]} exec -T db psql -U ${PG_USER} -d ${PG_DB}"
