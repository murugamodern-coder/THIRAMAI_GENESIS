#!/usr/bin/env bash
# Write .env.production on a Linux VPS (default: /root/thiramai-app/.env.production).
# Run from the app directory or set THIRAMAI_APP_ROOT.
# Generates SECRET_KEY if missing. Does not print secrets to stdout.

set -euo pipefail
ROOT="${THIRAMAI_APP_ROOT:-/root/thiramai-app}"
TARGET="${ROOT}/.env.production"
mkdir -p "$ROOT"
cd "$ROOT"

if [[ -f "$TARGET" && "${THIRAMAI_OVERWRITE_ENV:-0}" != "1" ]]; then
  echo "exists: $TARGET (set THIRAMAI_OVERWRITE_ENV=1 to replace)" >&2
  exit 0
fi

SK="${THIRAMAI_SECRET_KEY:-}"
if [[ -z "$SK" ]]; then
  SK="$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || openssl rand -base64 48 | tr -d '\n')"
fi

POSTGRES_PASSWORD="${THIRAMAI_POSTGRES_PASSWORD:-MyDB@123}"
# URL-encode @ in password for DATABASE_URL (literal %40)
ENC_PW="${POSTGRES_PASSWORD//@/%40}"
DATABASE_URL="${THIRAMAI_DATABASE_URL:-postgresql+psycopg2://thiramai:${ENC_PW}@db:5432/thiramai}"
CORS="${THIRAMAI_CORS_ORIGINS:-http://139.59.24.80}"

umask 077
cat >"$TARGET" <<EOF
ENV=production
THIRAMAI_ENV=production

POSTGRES_USER=thiramai
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=thiramai

DATABASE_URL=${DATABASE_URL}

SECRET_KEY=${SK}

THIRAMAI_CORS_ORIGINS=${CORS}

THIRAMAI_ENABLE_ALERT_SCHEDULER=1
REDIS_URL=redis://redis:6379/0

WEB_PORT=${WEB_PORT:-8000}
EOF

echo "wrote $TARGET"
