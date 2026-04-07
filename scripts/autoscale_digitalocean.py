#!/usr/bin/env python3
"""Cron-friendly entrypoint: ``python scripts/autoscale_digitalocean.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo root on path for ``services.*``
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.do_worker_autoscale import run_autoscale_once  # noqa: E402


def main() -> int:
    out = run_autoscale_once()
    print(json.dumps(out, indent=2, default=str))
    if out.get("error") and not out.get("skipped"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
