"""Redis-backed async queue adapter (RQ) with graceful fallback."""

from __future__ import annotations

import os
from typing import Any


def queue_mode() -> str:
    return (os.getenv("THIRAMAI_ASYNC_QUEUE_MODE") or "inline").strip().lower()


def use_rq_queue() -> bool:
    return queue_mode() == "rq"


def enqueue_task(task_name: str, payload: dict[str, Any], job_timeout: int | None = None) -> dict[str, Any]:
    """
    Enqueue to Redis RQ when enabled, else report inline mode.

    task_name must map to ``workers.async_tasks.<task_name>``.
    """
    if not use_rq_queue():
        return {"ok": True, "queued": False, "mode": "inline"}
    try:
        from redis import Redis
        from rq import Queue
    except Exception as exc:
        return {"ok": False, "queued": False, "mode": "rq", "error": f"RQ dependencies unavailable: {exc}"}

    redis_url = (os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip()
    queue_name = (os.getenv("THIRAMAI_RQ_QUEUE_NAME") or "thiramai").strip()
    conn = Redis.from_url(redis_url)
    q = Queue(queue_name, connection=conn)
    timeout = int(job_timeout) if job_timeout is not None else int((os.getenv("THIRAMAI_RQ_JOB_TIMEOUT_SECONDS") or "1800").strip())
    timeout = max(60, timeout)
    job = q.enqueue(f"workers.async_tasks.{task_name}", payload, job_timeout=timeout)
    return {"ok": True, "queued": True, "mode": "rq", "job_id": str(job.id)}
