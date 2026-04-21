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

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Do not override OS env (Docker Compose / k8s inject DATABASE_URL, etc.).
load_dotenv(dotenv_path=ROOT / ".env", override=False)
# Worker process needs cross-tenant access for global queue processing.
os.environ.setdefault("THIRAMAI_RLS_BYPASS", "1")

from core.observability import ensure_thiramai_logging, log_event, new_request_id
from core.worker_resilience import CircuitBreaker, ExponentialBackoff, WorkerHealthTracker
from services.job_queue import process_one_job, use_db_job_queue
from services.worker_heartbeat import touch_heartbeat

_log = logging.getLogger("thiramai.worker")

# Critical-storm guard: after this many consecutive DB/loop errors, escalate and clamp sleep.
_STORM_THRESHOLD = 10
_STORM_SLEEP_SEC = 300.0


def _emit_worker_cycle(
    *,
    jobs_processed: int,
    health: WorkerHealthTracker,
    breaker: CircuitBreaker,
) -> None:
    payload = {
        "event": "worker.cycle",
        "jobs_processed": jobs_processed,
        "consecutive_failures": health.consecutive_failures,
        "circuit_state": breaker.state.value,
        "total_failures": health.total_failures,
        "total_successes": health.total_successes,
        "healthy": health.is_healthy(),
    }
    _log.info(json.dumps(payload, separators=(",", ":")))


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
    breaker = CircuitBreaker()
    backoff = ExponentialBackoff()
    health = WorkerHealthTracker()

    rid = new_request_id()
    log_event(
        rid,
        "worker.startup",
        ok=True,
        extra={
            "poll_sec": poll,
            "job_queue_db": use_db_job_queue(),
            "circuit_breaker": "enabled",
            "backoff_max_sec": backoff.max_delay,
        },
    )

    while True:
        touch_heartbeat("job_worker")
        jobs_processed = 0

        if not breaker.can_execute():
            wait = breaker.seconds_until_half_open()
            sleep_for = max(0.2, min(wait if wait > 0 else poll, 60.0))
            time.sleep(sleep_for)
            _emit_worker_cycle(jobs_processed=0, health=health, breaker=breaker)
            continue

        try:
            worked = process_one_job()
            jobs_processed = 1 if worked else 0
            breaker.record_success()
            backoff.reset()
            health.record_success()
        except Exception as exc:
            breaker.record_failure()
            health.record_failure(str(exc))
            log_event(
                new_request_id(),
                "worker.loop_error",
                ok=False,
                error=str(exc),
                extra={"circuit_state": breaker.state.value},
            )
            delay = backoff.next_sleep()
            if health.consecutive_failures >= _STORM_THRESHOLD:
                delay = max(delay, _STORM_SLEEP_SEC)
                _log.critical(
                    json.dumps(
                        {
                            "event": "worker.storm_threshold",
                            "consecutive_failures": health.consecutive_failures,
                            "last_error": health.last_error,
                            "sleep_sec": delay,
                        },
                        separators=(",", ":"),
                    )
                )
            time.sleep(delay)
            _emit_worker_cycle(jobs_processed=jobs_processed, health=health, breaker=breaker)
            continue

        time.sleep(max(0.2, poll))
        _emit_worker_cycle(jobs_processed=jobs_processed, health=health, breaker=breaker)


if __name__ == "__main__":
    main()
