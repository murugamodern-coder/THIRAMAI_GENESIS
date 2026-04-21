#!/bin/bash
set -euo pipefail

# Verify static/command_center/index.html has hashed cc-app-*.js
SCRIPT=$(rg -o 'cc-app-[a-zA-Z0-9_-]+\.js' static/command_center/index.html || echo "")

if [ -z "$SCRIPT" ]; then
  echo "ERROR: index.html does not contain hashed cc-app-*.js!"
  echo "Static asset drift detected. Run npm run build first."
  exit 1
fi

echo "Static asset OK: $SCRIPT"
