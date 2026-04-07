"""
Phase 4 — autonomous AI decision automation (scheduled).

Registers an APScheduler job that calls ``services.decision_trigger.run_automation_scan_for_all_orgs``.

Enable with ``THIRAMAI_ENABLE_AUTOMATION_WORKER=1`` (requires ``THIRAMAI_ENABLE_ALERT_SCHEDULER=1`` so the
shared ``BackgroundScheduler`` is running — see ``workers.alert_system``).
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.observability import log_event, new_request_id

_log = logging.getLogger("thiramai.alert_worker")


def _truthy_env(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def _automation_interval_minutes() -> int:
    try:
        return max(5, int((os.getenv("THIRAMAI_AUTOMATION_INTERVAL_MINUTES") or "20").strip()))
    except ValueError:
        return 20


def register_automation_job(scheduler: BackgroundScheduler) -> None:
    """Attach ``run_automation_scan_for_all_orgs`` to an existing scheduler (single process)."""
    from services.decision_trigger import run_automation_scan_for_all_orgs

    minutes = _automation_interval_minutes()
    scheduler.add_job(
        run_automation_scan_for_all_orgs,
        IntervalTrigger(minutes=minutes),
        id="thiramai_automation_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    rid = new_request_id()
    log_event(
        rid,
        "alert_worker.automation_scheduled",
        ok=True,
        extra={"interval_minutes": minutes},
    )
    _log.info("automation job registered (every %s minutes)", minutes)


def run_automation_scan() -> None:
    """Manual / single-shot entry (same as scheduler callback)."""
    from services.decision_trigger import run_automation_scan_for_all_orgs

    run_automation_scan_for_all_orgs()


def automation_worker_enabled() -> bool:
    return _truthy_env("THIRAMAI_ENABLE_AUTOMATION_WORKER", "0")
