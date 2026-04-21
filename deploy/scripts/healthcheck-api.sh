#!/usr/bin/env sh
# THIRAMAI API liveness probe — suitable for cron (every 5 min) or external monitors.
# Exit 0 if live, 1 if down.
#
# Usage:
#   export HEALTH_URL=https://app.thiramai.co.in/health/live
#   ./healthcheck-api.sh
#
# Optional alerting (Slack/Discord incoming webhook JSON body):
#   export ALERT_WEBHOOK_URL=https://hooks.slack.com/services/xxx

set -eu

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health/live}"
UA="thiramai-healthcheck/1.0"

code="$(curl -fsS -o /dev/null -w "%{http_code}" -A "$UA" --max-time 15 "$HEALTH_URL" || echo "000")"

if [ "$code" = "200" ]; then
  exit 0
fi

msg="THIRAMAI health check FAILED: $HEALTH_URL returned HTTP $code at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

logger -t thiramai-health "$msg"

if [ -n "${ALERT_WEBHOOK_URL:-}" ] && command -v python3 >/dev/null 2>&1; then
  python3 -c "
import json, urllib.request, sys
url, text = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    url,
    data=json.dumps({'text': text}).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
)
urllib.request.urlopen(req, timeout=15)
" "$ALERT_WEBHOOK_URL" "$msg" || true
fi

exit 1
