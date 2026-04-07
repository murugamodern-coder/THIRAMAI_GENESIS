#!/usr/bin/env bash
# Detached tmux session for long-running AI / worker tasks (Linux, macOS, WSL).
#
# Usage:
#   chmod +x scripts/headless_tmux.sh
#   THIRAMAI_HEADLESS_CMD='python -m workers.run_worker' ./scripts/headless_tmux.sh
#   THIRAMAI_HEADLESS_SESSION=my-research ./scripts/headless_tmux.sh
#
# Attach later: tmux attach -t "${THIRAMAI_HEADLESS_SESSION:-thiramai-headless}"

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v tmux >/dev/null 2>&1; then
  echo "error: tmux not installed (e.g. apt install tmux / brew install tmux)" >&2
  exit 1
fi

SESSION="${THIRAMAI_HEADLESS_SESSION:-thiramai-headless}"
CMD="${THIRAMAI_HEADLESS_CMD:-python -m workers.run_worker}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "session '$SESSION' already exists — attach with: tmux attach -t $SESSION" >&2
  exit 1
fi

tmux new-session -d -s "$SESSION" -c "$ROOT" bash -lc "exec $CMD"
echo "started detached tmux session: $SESSION"
echo "attach: tmux attach -t $SESSION"
echo "logs:   tmux capture-pane -t $SESSION -p"
