"""
Distributed goal-job worker: claims ``dispatch_mode=worker`` rows from SQLite and runs them.

Requires ``THIRAMAI_WORKER_MODE=1``, ``THIRAMAI_JOB_SQLITE=1``, and API nodes submitting with
``THIRAMAI_GOAL_WORKER_DISPATCH=1``.

Run::

    set THIRAMAI_WORKER_MODE=1
    python -m thiramai.worker
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import time

log = logging.getLogger("thiramai.worker")


def main() -> None:
    from thiramai.config import THIRAMAI_JOB_SQLITE, THIRAMAI_VERSION_ID, THIRAMAI_WORKER_MODE, THIRAMAI_WORKER_POLL_SEC

    try:
        from thiramai.runtime.env_validate import validate_thiramai_environment

        validate_thiramai_environment(raise_on_error=True)
    except Exception as exc:
        sys.stderr.write(f"THIRAMAI environment validation failed: {exc}\n")
        raise SystemExit(2) from exc

    if not THIRAMAI_WORKER_MODE:
        sys.stderr.write(
            "Refusing to start: set THIRAMAI_WORKER_MODE=1 for the goal job worker "
            "(API must use THIRAMAI_GOAL_WORKER_DISPATCH=1 and THIRAMAI_JOB_SQLITE=1).\n"
        )
        raise SystemExit(2)

    if not THIRAMAI_JOB_SQLITE:
        sys.stderr.write("THIRAMAI_JOB_SQLITE must be enabled for the worker queue.\n")
        raise SystemExit(2)

    from core.observability import ensure_thiramai_logging

    ensure_thiramai_logging()

    poll = THIRAMAI_WORKER_POLL_SEC
    wid = (os.getenv("THIRAMAI_WORKER_ID") or "").strip() or f"{socket.gethostname()}-{os.getpid()}"

    from thiramai.runtime import goal_jobs
    from thiramai.runtime.sqlite_job_store import claim_next_worker_job, heartbeat_worker

    org_raw = (os.getenv("THIRAMAI_WORKER_ORG_ID") or "").strip()
    worker_org: int | None = int(org_raw) if org_raw.isdigit() else None
    if worker_org is None:
        log.warning(
            "THIRAMAI_WORKER_ORG_ID is not set; worker will process all pending worker-dispatch "
            "jobs (not recommended in production).",
        )

    goal_jobs.initialize_persistence()
    hb_sec = max(2.0, float(os.getenv("THIRAMAI_WORKER_HEARTBEAT_SEC", "5") or "5"))
    last_hb = 0.0
    log.info(
        "worker_started worker_id=%s poll_sec=%s heartbeat_sec=%s org=%s version_id=%s",
        wid,
        poll,
        hb_sec,
        worker_org,
        THIRAMAI_VERSION_ID,
    )

    while True:
        now = time.time()
        if now - last_hb >= hb_sec:
            heartbeat_worker(wid, "idle", None, organization_id=int(worker_org or 0))
            last_hb = now
        jid = claim_next_worker_job(wid, worker_org)
        if not jid:
            time.sleep(min(poll, hb_sec))
            continue
        log.info("claimed_job job_id=%s", jid)
        heartbeat_worker(wid, "busy", jid, organization_id=int(worker_org or 0))
        try:
            goal_jobs.run_persisted_job(jid)
        except Exception as exc:
            log.exception("job_failed job_id=%s err=%s", jid, exc)
        finally:
            heartbeat_worker(wid, "idle", None, organization_id=int(worker_org or 0))


if __name__ == "__main__":
    main()
