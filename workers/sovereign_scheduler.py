"""
Stage 5 global orchestrator jobs (APScheduler):

- World scan every 4 hours per active organization
- Daily executive summary (Minute Office)

Enable with ``THIRAMAI_SOVEREIGN_SCHEDULER=1`` (started from ``app.py`` alongside alert scheduler).
Standalone: ``python -m workers.sovereign_scheduler``
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_session_factory, session_scope
from core.db.models import Organization, User, UserOrganizationMembership
from core.observability import ensure_thiramai_logging, log_event, new_request_id
from services.empire_governance import build_pl_vs_market_analysis, build_weekly_revenue_opportunity
from services.infra_self_heal import run_self_heal_scan
from services.prompt_self_tune import run_prompt_self_analysis
from services.task_aggregator import build_daily_executive_summary
from services.world_scanner import run_world_scan_for_org

_log = logging.getLogger("thiramai.sovereign_scheduler")

_scheduler: BackgroundScheduler | None = None


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def sovereign_scheduler_enabled() -> bool:
    return _truthy("THIRAMAI_SOVEREIGN_SCHEDULER")


def empire_governance_jobs_enabled() -> bool:
    return _truthy("THIRAMAI_EMPIRE_GOVERNANCE_MODE")


def _active_org_ids(session: Session) -> list[int]:
    stmt = (
        select(Organization.id)
        .distinct()
        .join(UserOrganizationMembership, UserOrganizationMembership.organization_id == Organization.id)
        .join(User, User.id == UserOrganizationMembership.user_id)
        .where(User.is_active.is_(True), UserOrganizationMembership.is_active.is_(True))
    )
    return [int(x) for x in session.scalars(stmt).all()]


def run_world_scan_all_orgs() -> None:
    rid = new_request_id()
    factory = get_session_factory()
    if factory is None:
        log_event(rid, "sovereign.world_scan", ok=False, extra={"reason": "no_database"})
        return
    try:
        with session_scope() as session:
            org_ids = _active_org_ids(session)
        allow = (os.getenv("THIRAMAI_SOVEREIGN_ORG_IDS") or "").strip()
        if allow:
            wanted = {int(x) for x in allow.split(",") if x.strip().isdigit()}
            org_ids = [i for i in org_ids if i in wanted]
        for oid in org_ids:
            try:
                run_world_scan_for_org(oid)
            except Exception as exc:
                _log.warning("sovereign.world_scan org=%s failed: %s", oid, exc)
        log_event(
            rid,
            "sovereign.world_scan",
            ok=True,
            extra={"organizations": len(org_ids)},
        )
    except Exception as exc:
        _log.exception("sovereign.world_scan_failed")
        log_event(rid, "sovereign.world_scan", ok=False, error=str(exc))


def run_executive_summary_all_orgs() -> None:
    rid = new_request_id()
    factory = get_session_factory()
    if factory is None:
        log_event(rid, "sovereign.executive_summary", ok=False, extra={"reason": "no_database"})
        return
    try:
        with session_scope() as session:
            org_ids = _active_org_ids(session)
        allow = (os.getenv("THIRAMAI_SOVEREIGN_ORG_IDS") or "").strip()
        if allow:
            wanted = {int(x) for x in allow.split(",") if x.strip().isdigit()}
            org_ids = [i for i in org_ids if i in wanted]
        for oid in org_ids:
            try:
                build_daily_executive_summary(oid)
            except Exception as exc:
                _log.warning("sovereign.executive_summary org=%s failed: %s", oid, exc)
        log_event(
            rid,
            "sovereign.executive_summary",
            ok=True,
            extra={"organizations": len(org_ids)},
        )
    except Exception as exc:
        _log.exception("sovereign.executive_summary_failed")
        log_event(rid, "sovereign.executive_summary", ok=False, error=str(exc))


def run_pl_governance_all_orgs() -> None:
    if not empire_governance_jobs_enabled():
        return
    rid = new_request_id()
    factory = get_session_factory()
    if factory is None:
        return
    try:
        with session_scope() as session:
            org_ids = _active_org_ids(session)
        allow = (os.getenv("THIRAMAI_SOVEREIGN_ORG_IDS") or "").strip()
        if allow:
            wanted = {int(x) for x in allow.split(",") if x.strip().isdigit()}
            org_ids = [i for i in org_ids if i in wanted]
        for oid in org_ids:
            try:
                build_pl_vs_market_analysis(oid)
            except Exception as exc:
                _log.warning("sovereign.pl_governance org=%s failed: %s", oid, exc)
        log_event(rid, "sovereign.pl_governance", ok=True, extra={"organizations": len(org_ids)})
    except Exception as exc:
        _log.exception("sovereign.pl_governance_failed")
        log_event(rid, "sovereign.pl_governance", ok=False, error=str(exc))


def run_weekly_opportunity_all_orgs() -> None:
    if not empire_governance_jobs_enabled():
        return
    rid = new_request_id()
    factory = get_session_factory()
    if factory is None:
        return
    try:
        with session_scope() as session:
            org_ids = _active_org_ids(session)
        allow = (os.getenv("THIRAMAI_SOVEREIGN_ORG_IDS") or "").strip()
        if allow:
            wanted = {int(x) for x in allow.split(",") if x.strip().isdigit()}
            org_ids = [i for i in org_ids if i in wanted]
        for oid in org_ids:
            try:
                build_weekly_revenue_opportunity(oid)
            except Exception as exc:
                _log.warning("sovereign.weekly_opportunity org=%s failed: %s", oid, exc)
        log_event(rid, "sovereign.weekly_opportunity", ok=True, extra={"organizations": len(org_ids)})
    except Exception as exc:
        _log.exception("sovereign.weekly_opportunity_failed")
        log_event(rid, "sovereign.weekly_opportunity", ok=False, error=str(exc))


def run_prompt_tuning_job() -> None:
    if not empire_governance_jobs_enabled():
        return
    rid = new_request_id()
    try:
        run_prompt_self_analysis(organization_id=None)
        log_event(rid, "sovereign.prompt_tuning", ok=True, extra={})
    except Exception as exc:
        _log.exception("sovereign.prompt_tuning_failed")
        log_event(rid, "sovereign.prompt_tuning", ok=False, error=str(exc))


def run_self_heal_job() -> None:
    rid = new_request_id()
    try:
        out = run_self_heal_scan()
        log_event(rid, "sovereign.self_heal_tick", ok=True, extra={"result_keys": list(out.keys())})
    except Exception as exc:
        _log.exception("sovereign.self_heal_failed")
        log_event(rid, "sovereign.self_heal_tick", ok=False, error=str(exc))


def run_jarvis_proactive_morning() -> None:
    """7:00 Asia/Kolkata — subsidy / EMI / overdue / idle machine alerts into ``jarvis_proactive_alerts``."""
    rid = new_request_id()
    try:
        from workers.morning_intelligence_worker import run_morning_intelligence_once

        out = run_morning_intelligence_once()
        log_event(rid, "jarvis.proactive_morning", ok=True, extra=out)
    except Exception as exc:
        _log.exception("jarvis.proactive_morning_failed")
        log_event(rid, "jarvis.proactive_morning", ok=False, error=str(exc))


def jarvis_realtime_scheduler_enabled() -> bool:
    return (os.getenv("THIRAMAI_JARVIS_REALTIME_SCHEDULER") or "1").strip().lower() in ("1", "true", "yes", "on")


def run_jarvis_proactive_realtime() -> None:
    """Every 15m — meetings soon + strong watchlist signals (IST business + market hours)."""
    rid = new_request_id()
    try:
        from workers.realtime_check_worker import run_realtime_checks_once

        out = run_realtime_checks_once()
        log_event(rid, "jarvis.proactive_realtime", ok=True, extra=out)
    except Exception as exc:
        _log.exception("jarvis.proactive_realtime_failed")
        log_event(rid, "jarvis.proactive_realtime", ok=False, error=str(exc))


def jarvis_autonomous_scheduler_enabled() -> bool:
    """Upgrade 2.2 — periodic goal/plan execution ticks (safe, rate-limited per user)."""
    return _truthy("THIRAMAI_JARVIS_AUTONOMOUS_SCHEDULER")


def run_jarvis_autonomous_tick() -> None:
    rid = new_request_id()
    try:
        from services.jarvis_autonomous_agent import run_autonomous_cycle_all_users_sync

        out = run_autonomous_cycle_all_users_sync()
        log_event(rid, "jarvis.autonomous_tick", ok=True, extra=out)
    except Exception as exc:
        _log.exception("jarvis.autonomous_tick_failed")
        log_event(rid, "jarvis.autonomous_tick", ok=False, error=str(exc))


def run_jarvis_autonomous_morning_bundle() -> None:
    """07:10 Asia/Kolkata — persist Today's Plan + one autonomous cycle per active user."""
    rid = new_request_id()
    try:
        from services.jarvis_autonomous_agent import run_jarvis_autonomous_morning_bundle_sync

        out = run_jarvis_autonomous_morning_bundle_sync()
        log_event(rid, "jarvis.autonomous_morning", ok=True, extra=out)
    except Exception as exc:
        _log.exception("jarvis.autonomous_morning_failed")
        log_event(rid, "jarvis.autonomous_morning", ok=False, error=str(exc))


def jarvis_event_queue_drain_enabled() -> bool:
    """Process ``jarvis_agent_event_queue`` rows (e.g. from PostgreSQL triggers)."""
    return _truthy("THIRAMAI_JARVIS_EVENT_QUEUE_DRAIN")


def run_jarvis_event_queue_drain() -> None:
    rid = new_request_id()
    try:
        from services.jarvis_agent_event_engine import drain_agent_event_queue_sync

        out = drain_agent_event_queue_sync(limit=40)
        log_event(rid, "jarvis.event_queue_drain", ok=True, extra=out)
    except Exception as exc:
        _log.exception("jarvis.event_queue_drain_failed")
        log_event(rid, "jarvis.event_queue_drain", ok=False, error=str(exc))


def start_sovereign_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not sovereign_scheduler_enabled():
        return None
    if get_session_factory() is None:
        _log.warning("sovereign_scheduler: DATABASE_URL not set; not started")
        return None

    sched = BackgroundScheduler(timezone="UTC")
    hours = 4
    try:
        hours = max(1, min(24, int((os.getenv("THIRAMAI_WORLD_SCAN_INTERVAL_HOURS") or "4").strip())))
    except ValueError:
        hours = 4
    sched.add_job(
        run_world_scan_all_orgs,
        IntervalTrigger(hours=hours),
        id="thiramai_world_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Daily digest — default 05:30 UTC
    h, m = 5, 30
    raw_cron = (os.getenv("THIRAMAI_EXECUTIVE_SUMMARY_CRON") or "30 5 * * *").strip().split()
    if len(raw_cron) >= 2 and raw_cron[0].isdigit() and raw_cron[1].isdigit():
        m, h = int(raw_cron[0]), int(raw_cron[1])
    sched.add_job(
        run_executive_summary_all_orgs,
        CronTrigger(hour=h, minute=m),
        id="thiramai_executive_summary",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if empire_governance_jobs_enabled():
        sched.add_job(
            run_pl_governance_all_orgs,
            CronTrigger(hour=6, minute=20),
            id="thiramai_pl_governance",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        sched.add_job(
            run_weekly_opportunity_all_orgs,
            CronTrigger(day_of_week="mon", hour=7, minute=5),
            id="thiramai_weekly_opportunity",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        sched.add_job(
            run_prompt_tuning_job,
            CronTrigger(day_of_week="sun", hour=3, minute=0),
            id="thiramai_prompt_self_tune",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    sched.add_job(
        run_self_heal_job,
        IntervalTrigger(minutes=5),
        id="thiramai_self_heal_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        run_jarvis_proactive_morning,
        CronTrigger(hour=7, minute=0, timezone="Asia/Kolkata"),
        id="thiramai_jarvis_proactive_morning",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if jarvis_realtime_scheduler_enabled():
        sched.add_job(
            run_jarvis_proactive_realtime,
            IntervalTrigger(minutes=15),
            id="thiramai_jarvis_proactive_realtime",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    sched.add_job(
        run_jarvis_autonomous_morning_bundle,
        CronTrigger(hour=7, minute=10, timezone="Asia/Kolkata"),
        id="thiramai_jarvis_autonomous_morning",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if jarvis_autonomous_scheduler_enabled():
        sched.add_job(
            run_jarvis_autonomous_tick,
            IntervalTrigger(minutes=30),
            id="thiramai_jarvis_autonomous_tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if jarvis_event_queue_drain_enabled():
        sched.add_job(
            run_jarvis_event_queue_drain,
            IntervalTrigger(minutes=2),
            id="thiramai_jarvis_event_queue_drain",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    sched.start()
    _scheduler = sched
    log_event(
        new_request_id(),
        "sovereign.scheduler_started",
        ok=True,
        extra={
            "world_scan_hours": hours,
            "executive_summary_utc": f"{h:02d}:{m:02d}",
            "empire_governance": empire_governance_jobs_enabled(),
        },
    )
    return _scheduler


def shutdown_sovereign_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


if __name__ == "__main__":
    ensure_thiramai_logging()
    os.environ.setdefault("THIRAMAI_SOVEREIGN_SCHEDULER", "1")
    s = start_sovereign_scheduler()
    if s is None:
        raise SystemExit("scheduler not started (enable THIRAMAI_SOVEREIGN_SCHEDULER=1 and DATABASE_URL)")
    print("Sovereign scheduler running. Ctrl+C to stop.")
    try:
        while True:
            import time

            time.sleep(3600)
    except KeyboardInterrupt:
        shutdown_sovereign_scheduler()
