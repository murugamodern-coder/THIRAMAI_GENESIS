#!/usr/bin/env bash
# Create .env.production from template and rotate SECRET_KEY / JWT_SECRET_KEY.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Setting up .env.production..."

if [[ -f .env.production ]]; then
  echo "WARNING: .env.production already exists."
  read -r -p "Overwrite? (yes/no): " CONFIRM
  if [[ "$CONFIRM" != "yes" ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

cp .env.production.example .env.production

echo ""
echo "Generating SECRET_KEY and JWT_SECRET_KEY..."

PYEXE="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [[ -z "$PYEXE" ]]; then
  echo "ERROR: python not found on PATH"
  exit 1
fi

"$PYEXE" - <<'PY'
import re
import secrets
from pathlib import Path

path = Path(".env.production")
text = path.read_text(encoding="utf-8", errors="replace")
for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
    val = secrets.token_urlsafe(32)
    pat = re.compile(rf"^{key}=.*$", re.M)
    if not pat.search(text):
        continue
    text = pat.sub(f"{key}={val}", text, count=1)
path.write_text(text, encoding="utf-8")
print("Updated SECRET_KEY and JWT_SECRET_KEY in .env.production")
PY

echo ""
echo "OK: .env.production created."
echo ""
echo "IMPORTANT: Edit .env.production and set at least:"
echo "  - POSTGRES_PASSWORD + DATABASE_URL (matching credentials)"
echo "  - THIRAMAI_CORS_ORIGINS (real HTTPS origins in production)"
echo "  - GROQ_API_KEY / TAVILY_API_KEY if you need chat"
echo ""
grep -E "^(THIRAMAI_DECISION_AB_TEST|DECISION_AB_TEST|POOL_SIZE|MAX_OVERFLOW|JWT_SECRET_KEY)=" .env.production 2>/dev/null || true
