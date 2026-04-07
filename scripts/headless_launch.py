"""
Pick tmux or screen for a detached long-running command (no interactive TTY required).

On native Windows without WSL, use Task Scheduler or ``start /B`` instead; this script exits with a hint.

Usage:
  python scripts/headless_launch.py -- python -m workers.run_worker
  THIRAMAI_HEADLESS_BACKEND=screen python scripts/headless_launch.py -- your-command args
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    if "--" not in sys.argv:
        print("usage: python scripts/headless_launch.py -- <command> [args...]", file=sys.stderr)
        return 2
    idx = sys.argv.index("--")
    inner = sys.argv[idx + 1 :]
    if not inner:
        print("error: no command after --", file=sys.stderr)
        return 2
    cmd_str = subprocess.list2cmdline(inner)

    if sys.platform == "win32" and not os.environ.get("WSL_DISTRO_NAME"):
        print(
            "Native Windows: use WSL and run scripts/headless_tmux.sh, "
            "or Task Scheduler / `start /B` for background work.",
            file=sys.stderr,
        )
        return 1

    backend = (os.getenv("THIRAMAI_HEADLESS_BACKEND") or "tmux").strip().lower()
    root = _root()
    env = os.environ.copy()
    env["THIRAMAI_HEADLESS_CMD"] = cmd_str

    if backend == "screen":
        script = root / "scripts" / "headless_screen.sh"
        argv = ["bash", str(script)]
    else:
        script = root / "scripts" / "headless_tmux.sh"
        argv = ["bash", str(script)]

    if not script.is_file():
        print(f"error: missing {script}", file=sys.stderr)
        return 1
    return subprocess.call(argv, cwd=str(root), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
