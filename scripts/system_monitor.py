#!/usr/bin/env python3
"""
Ops helper: exit non-zero if ``job_worker`` Redis heartbeat is stale (> 5 minutes).

Requires ``REDIS_URL``. Intended for cron / external monitoring.

Usage::

    python scripts/system_monitor.py
    echo $?
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env", override=True)

STALE_SEC = 300.0


def main() -> int:
    from core.observability import ensure_thiramai_logging, log_structured
    from services.worker_heartbeat import job_worker_heartbeat_age_seconds

    ensure_thiramai_logging()
    age, msg = job_worker_heartbeat_age_seconds()
    if age is None:
        log_structured(
            "system_monitor.job_worker",
            ok=False,
            reason="missing_or_stale",
            detail=msg,
        )
        return 1
    if age > STALE_SEC:
        log_structured(
            "system_monitor.job_worker",
            ok=False,
            reason="stale",
            age_seconds=round(age, 2),
            limit_seconds=STALE_SEC,
            detail=msg,
        )
        return 1
    log_structured(
        "system_monitor.job_worker",
        ok=True,
        age_seconds=round(age, 2),
        detail=msg,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
