#!/usr/bin/env bash
# Detached GNU screen session for long-running tasks (common on servers without tmux).
#
# Usage:
#   chmod +x scripts/headless_screen.sh
#   THIRAMAI_HEADLESS_CMD='python -m workers.run_worker' ./scripts/headless_screen.sh
#
# Reattach: screen -r thiramai-headless

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v screen >/dev/null 2>&1; then
  echo "error: screen not installed (e.g. apt install screen)" >&2
  exit 1
fi

NAME="${THIRAMAI_HEADLESS_SESSION:-thiramai-headless}"
CMD="${THIRAMAI_HEADLESS_CMD:-python -m workers.run_worker}"

screen -dmS "$NAME" bash -lc "cd \"$ROOT\" && exec $CMD"
echo "started detached screen session: $NAME"
echo "list:   screen -ls"
echo "attach: screen -r $NAME"
