#!/usr/bin/env bash
# Dry-run logrotate for THIRAMAI nginx logs (requires sudo on the server).
# Usage: sudo ./verify-logrotate.sh

set -euo pipefail

CONF="${1:-/etc/logrotate.d/nginx-thiramai}"

if [[ ! -f "$CONF" ]]; then
  echo "Missing $CONF — install deploy/logrotate/nginx-thiramai.conf first." >&2
  exit 1
fi

echo "Testing logrotate config: $CONF"
logrotate -d "$CONF"
echo "Dry-run OK (no files rotated)."
