"""
Living Jarvis Upgrade 2 — realtime checks (meetings soon, strong stock signals).

Runs on a short interval during IST business hours (scheduler + optional DB job queue).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def run_realtime_checks_once() -> dict[str, Any]:
    from services.jarvis_proactive_service import run_realtime_job_all_users_sync
    from services.job_queue import enqueue_jarvis_proactive_scan, use_db_job_queue

    if use_db_job_queue():
        now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(second=0, microsecond=0)
        minute = (now.minute // 15) * 15
        slot = now.replace(minute=minute)
        jid = enqueue_jarvis_proactive_scan(
            kind="realtime",
            idempotency_key=f"jarvis_proactive_realtime:{slot.isoformat()}",
        )
        return {"ok": True, "enqueued": True, "job_id": jid}
    return run_realtime_job_all_users_sync()


if __name__ == "__main__":
    from core.observability import ensure_thiramai_logging

    ensure_thiramai_logging()
    print(run_realtime_checks_once())
