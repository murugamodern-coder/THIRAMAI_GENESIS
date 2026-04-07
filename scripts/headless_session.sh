#!/usr/bin/env bash
# Headless long-running tasks (research, code-gen loops) via tmux or screen.
#
# Usage:
#   ./scripts/headless_session.sh 'python -m workers.run_worker'
#   THIRAMAI_HEADLESS_SESSION=my-research ./scripts/headless_session.sh 'python scripts/foo.py'
#
# Attach: tmux attach -t "${THIRAMAI_HEADLESS_SESSION:-thiramai-ai}"
#         screen -r "${THIRAMAI_HEADLESS_SESSION:-thiramai-ai}"
#
# On Windows, use WSL or Git Bash where tmux/screen is installed.

set -euo pipefail

SESSION="${THIRAMAI_HEADLESS_SESSION:-thiramai-ai}"
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 '<command string>'" >&2
  exit 1
fi
CMD="$*"
LOG_DIR="${THIRAMAI_HEADLESS_LOG_DIR:-var/headless}"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/${SESSION}-${STAMP}.log"

if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already exists. Attach with: tmux attach -t $SESSION" >&2
    exit 1
  fi
  # shellcheck disable=SC2016
  tmux new-session -ds "$SESSION" bash -lc "exec > >(tee -a '$LOG_FILE') 2>&1; $CMD"
  echo "Started tmux session '$SESSION' (log: $LOG_FILE). Attach: tmux attach -t $SESSION"
elif command -v screen >/dev/null 2>&1; then
  screen -dmS "$SESSION" bash -lc "exec > >(tee -a '$LOG_FILE') 2>&1; $CMD"
  echo "Started screen session '$SESSION' (log: $LOG_FILE). Attach: screen -r $SESSION"
else
  echo "Neither tmux nor screen found in PATH." >&2
  exit 1
fi
