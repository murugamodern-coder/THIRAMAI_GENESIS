"""
Autonomous AI layer worker (scheduled):

- Evaluates pending AI decisions
- Applies per-org autonomy policy
- Auto-executes low-risk actions
- Alerts for operator/admin approval when needed

Enable via:
  THIRAMAI_ENABLE_AUTONOMY_ENGINE=1
  THIRAMAI_ENABLE_ALERT_SCHEDULER=1  (shared APScheduler process)
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.observability import log_event, new_request_id

_log = logging.getLogger("thiramai.autonomy_worker")


def _truthy_env(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def autonomy_engine_enabled() -> bool:
    return _truthy_env("THIRAMAI_ENABLE_AUTONOMY_ENGINE", "0")


def _interval_minutes() -> int:
    try:
        return max(1, int((os.getenv("THIRAMAI_AUTONOMY_INTERVAL_MINUTES") or "2").strip()))
    except ValueError:
        return 2


def register_autonomy_job(scheduler: BackgroundScheduler) -> None:
    from services.auto_action_engine import run_autonomy_cycle_for_all_orgs

    minutes = _interval_minutes()
    scheduler.add_job(
        run_autonomy_cycle_for_all_orgs,
        IntervalTrigger(minutes=minutes),
        id="thiramai_autonomy_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    rid = new_request_id()
    log_event(rid, "autonomy_worker.scheduled", ok=True, extra={"interval_minutes": minutes})
    _log.info("autonomy job registered (every %s minutes)", minutes)

