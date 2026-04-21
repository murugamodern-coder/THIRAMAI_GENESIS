"""Operational alerting: failure bursts, worker health, queue backlog."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

_log = logging.getLogger("thiramai.ops_alert")

_alert_thread: threading.Thread | None = None
_alert_stop = threading.Event()

# 0 = disabled (total failure counter is lifetime — enable only with care).
FAILURE_BURST_THRESHOLD = max(0, int(os.getenv("THIRAMAI_OPS_ALERT_FAILURE_BURST", "0") or "0"))
QUEUE_BACKLOG_THRESHOLD = max(5, int(os.getenv("THIRAMAI_OPS_ALERT_QUEUE_DEPTH", "25") or "25"))
WORKER_DEAD_SEC = max(15.0, float(os.getenv("THIRAMAI_OPS_ALERT_WORKER_DEAD_SEC", "45") or "45"))
WEBHOOK_URL = (os.getenv("THIRAMAI_OPS_ALERT_WEBHOOK_URL") or "").strip()


def emit_slow_goal_job(job_id: str, execution_ms: float, threshold_ms: float) -> None:
    """Webhook + structured log when a goal job exceeds wall-clock threshold (phase 52)."""
    _emit(
        "warning",
        "slow_goal_job",
        {"job_id": job_id, "execution_ms": execution_ms, "threshold_ms": threshold_ms},
    )


def _emit(level: str, event: str, payload: dict[str, Any]) -> None:
    body = {
        "timestamp": time.time(),
        "event": event,
        "status": level,
        "module": "thiramai.ops_alert",
        **payload,
    }
    line = json.dumps(body, ensure_ascii=False, default=str)
    if level == "critical":
        _log.error("%s", line)
    elif level == "warning":
        _log.warning("%s", line)
    else:
        _log.info("%s", line)
    if WEBHOOK_URL:
        try:
            req = urllib.request.Request(
                WEBHOOK_URL,
                data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5.0)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            pass


def check_once() -> None:
    from thiramai.runtime import ai_observability
    from thiramai.runtime import goal_jobs

    snap = ai_observability.snapshot_counters()
    fails = int(snap.get("failures_recorded_total") or 0)
    if FAILURE_BURST_THRESHOLD > 0 and fails >= FAILURE_BURST_THRESHOLD:
        _emit(
            "warning",
            "failure_burst",
            {"failures_recorded_total": fails, "threshold": FAILURE_BURST_THRESHOLD},
        )

    q = goal_jobs.queue_snapshot()
    pending_n = len(q.get("pending") or [])
    if pending_n >= QUEUE_BACKLOG_THRESHOLD:
        _emit(
            "warning",
            "queue_backlog",
            {"pending_jobs": pending_n, "threshold": QUEUE_BACKLOG_THRESHOLD},
        )

    try:
        from thiramai.runtime.sqlite_job_store import list_worker_heartbeats

        now = time.time()
        for row in list_worker_heartbeats():
            wid = str(row.get("worker_id") or "")
            ts = float(row.get("ts") or 0)
            if wid and now - ts > WORKER_DEAD_SEC:
                _emit(
                    "critical",
                    "worker_stale",
                    {
                        "worker_id": wid,
                        "last_seen_age_sec": round(now - ts, 1),
                        "threshold_sec": WORKER_DEAD_SEC,
                    },
                )
    except Exception:
        pass


def _loop(interval_sec: float) -> None:
    while not _alert_stop.wait(timeout=interval_sec):
        try:
            check_once()
        except Exception:
            _log.exception("ops_alert.check_once failed")


def start_background_checks(interval_sec: float = 60.0) -> None:
    global _alert_thread
    if _alert_thread and _alert_thread.is_alive():
        return
    _alert_stop.clear()
    _alert_thread = threading.Thread(
        target=_loop,
        args=(max(15.0, float(interval_sec)),),
        name="thiramai-ops-alerts",
        daemon=True,
    )
    _alert_thread.start()


def stop_background_checks() -> None:
    _alert_stop.set()
