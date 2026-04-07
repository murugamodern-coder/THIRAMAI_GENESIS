"""
Standalone worker process: drain ``background_jobs`` (``THIRAMAI_JOB_QUEUE=db``).

Usage::

    export DATABASE_URL=postgresql+psycopg2://...
    export THIRAMAI_JOB_QUEUE=db
    python -m workers.run_worker

API servers should use the same ``DATABASE_URL`` and ``THIRAMAI_JOB_QUEUE=db`` so approvals
enqueue rows instead of running ``BackgroundTasks`` in-process.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env", override=True)

from core.observability import ensure_thiramai_logging, log_event, new_request_id
from services.job_queue import process_one_job, use_db_job_queue
from services.worker_heartbeat import touch_heartbeat


def main() -> None:
    ensure_thiramai_logging()
    if not use_db_job_queue():
        log_event(
            new_request_id(),
            "worker.config_warning",
            ok=False,
            error="THIRAMAI_JOB_QUEUE is not 'db'; API may still use inline BackgroundTasks.",
            extra={"hint": "Set THIRAMAI_JOB_QUEUE=db on API and worker for DB queue mode."},
        )
    poll = float((os.getenv("THIRAMAI_WORKER_POLL_SEC") or "2").strip())
    rid = new_request_id()
    log_event(
        rid,
        "worker.startup",
        ok=True,
        extra={"poll_sec": poll, "job_queue_db": use_db_job_queue()},
    )
    while True:
        touch_heartbeat("job_worker")
        try:
            if process_one_job():
                continue
        except Exception as exc:
            log_event(
                new_request_id(),
                "worker.loop_error",
                ok=False,
                error=str(exc),
            )
        time.sleep(max(0.2, poll))


if __name__ == "__main__":
    main()
