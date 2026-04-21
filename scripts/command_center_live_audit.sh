#!/usr/bin/env bash
# Audit Command Center assets on a running API (production or local).
#
# Usage:
#   ./scripts/command_center_live_audit.sh [BASE_URL]
# Example:
#   ./scripts/command_center_live_audit.sh https://app.thiramai.co.in
#   ./scripts/command_center_live_audit.sh http://127.0.0.1:8000
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
BASE="${BASE%/}"

echo "=============================================="
echo "Command Center live audit — ${BASE}"
echo "=============================================="

echo ""
echo "=== 1) index.html — response headers (Cache-Control must be no-store) ==="
curl -fsS -D - -o /tmp/thiramai-cc-index.html "${BASE}/static/command_center/index.html" | tr -d '\r' | sed -n '1,25p'

echo ""
echo "=== 2) index.html — script tags (must be cc-app-<hash>.js only; no cc-app.js, no ?v= on script src) ==="
grep -Eo 'src="[^"]+"' /tmp/thiramai-cc-index.html || true
if grep -q 'cc-app\.js' /tmp/thiramai-cc-index.html; then
  echo "FAIL: index references legacy cc-app.js"
else
  echo "OK: no literal cc-app.js in index"
fi
if grep -q '\?v=' /tmp/thiramai-cc-index.html; then
  echo "NOTE: ?v= found in index body (unusual for Vite; verify manually)"
else
  echo "OK: no ?v= in index body (expected; hashes bust JS)"
fi

echo ""
echo "=== 3) GET /health/command-center-index (must report ok:true and bundle_style:content_hashed) ==="
curl -fsS "${BASE}/health/command-center-index" || echo "(failed — old image or Nginx not proxying API)"

echo ""
echo "=== 3b) GET /api/system/command-center-build (optional shell ?v= for redirects) ==="
curl -fsS "${BASE}/api/system/command-center-build" || echo "(failed — old image)"

echo ""
echo "=== 4) GET / — redirect Location (may include ?v= when THIRAMAI_COMMAND_CENTER_BUILD_ID is set) ==="
curl -fsS -D - -o /dev/null "${BASE}/" | tr -d '\r' | grep -i '^location:' || true

echo ""
echo "=== 5) Exact index.html body (full file at /tmp/thiramai-cc-index.html) ==="
wc -c /tmp/thiramai-cc-index.html
cat /tmp/thiramai-cc-index.html

echo ""
echo "=== Done ==="
