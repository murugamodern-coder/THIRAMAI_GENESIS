"""
Living Jarvis Upgrade 2 — morning intelligence batch.

Intended for ``THIRAMAI_SOVEREIGN_SCHEDULER=1`` (default 07:00 Asia/Kolkata). When
``THIRAMAI_JOB_QUEUE=db``, enqueues a ``jarvis_proactive`` morning job for ``workers.run_worker``;
otherwise runs ``run_morning_job_all_users_sync`` inline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def run_morning_intelligence_once() -> dict[str, Any]:
    from services.jarvis_proactive_service import run_morning_job_all_users_sync
    from services.job_queue import enqueue_jarvis_proactive_scan, use_db_job_queue

    if use_db_job_queue():
        ist_day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        jid = enqueue_jarvis_proactive_scan(
            kind="morning",
            idempotency_key=f"jarvis_proactive_morning:{ist_day}",
        )
        return {"ok": True, "enqueued": True, "job_id": jid}
    return run_morning_job_all_users_sync()


if __name__ == "__main__":
    from core.observability import ensure_thiramai_logging

    ensure_thiramai_logging()
    print(run_morning_intelligence_once())
