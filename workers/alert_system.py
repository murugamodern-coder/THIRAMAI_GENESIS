"""
Periodic tenant-aware alerts: low inventory and overdue debts → PostgreSQL `notifications`.

- **Active organizations:** at least one active ``UserOrganizationMembership`` for an active user.
- **Low stock:** `inventory.quantity` ≤ `THIRAMAI_ALERT_LOW_STOCK_THRESHOLD` (default 10).
- **Overdue debt:** `debts.due_date` is set and before today (UTC).

Schedule with APScheduler. Run embedded from FastAPI (`THIRAMAI_ENABLE_ALERT_SCHEDULER=1`) or standalone:

    python -m workers.alert_system

Apply DDL: `db/notifications_alerts.sql` (or use fresh `db/db_schema.sql` which includes notifications).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.database import get_session_factory, session_scope
from core.db.models import Debt, Inventory, Notification, Organization, User, UserOrganizationMembership
from core.observability import ensure_thiramai_logging, log_event, new_request_id
from core.worker_resilience import CircuitBreaker, ExponentialBackoff, WorkerHealthTracker

_log = logging.getLogger("thiramai.alert_system")
# Alert worker scans across all organizations and must bypass tenant RLS policies.
os.environ.setdefault("THIRAMAI_RLS_BYPASS", "1")

_scheduler: BackgroundScheduler | None = None

# Resilience (shared by embedded API scheduler and standalone ``python -m workers.alert_system``)
_alert_circuit = CircuitBreaker()
_alert_health = WorkerHealthTracker()
_alert_backoff: ExponentialBackoff | None = None
_alert_scan_suppress_until: float = 0.0

NOTIFICATION_CONSTRAINT = "uq_notifications_org_dedupe"


def _truthy_env(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def _low_stock_threshold() -> Decimal:
    raw = (os.getenv("THIRAMAI_ALERT_LOW_STOCK_THRESHOLD") or "10").strip()
    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal("10")


def _interval_minutes() -> int:
    try:
        return max(1, int((os.getenv("THIRAMAI_ALERT_INTERVAL_MINUTES") or "15").strip()))
    except ValueError:
        return 15


def _alert_backoff_instance() -> ExponentialBackoff:
    """Max backoff is min(30m, one scheduler interval) so we do not oversleep the next tick."""
    global _alert_backoff
    if _alert_backoff is None:
        interval_sec = float(_interval_minutes() * 60)
        cap = min(1800.0, interval_sec)
        _alert_backoff = ExponentialBackoff(max_delay=cap)
    return _alert_backoff


def _org_id_allowlist() -> set[int] | None:
    raw = (os.getenv("THIRAMAI_ALERT_ORG_IDS") or "").strip()
    if not raw:
        return None
    out: set[int] = set()
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit():
            out.add(int(p))
    return out or None


def active_organization_ids(session: Session) -> list[int]:
    """
    Organizations that have at least one active user with an active membership row.
    """
    stmt = (
        select(Organization.id)
        .distinct()
        .join(UserOrganizationMembership, UserOrganizationMembership.organization_id == Organization.id)
        .join(User, User.id == UserOrganizationMembership.user_id)
        .where(
            User.is_active.is_(True),
            UserOrganizationMembership.is_active.is_(True),
        )
    )
    ids = [int(x) for x in session.scalars(stmt).all()]
    allow = _org_id_allowlist()
    if allow is not None:
        ids = [i for i in ids if i in allow]
    return ids


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _notify_low_stock(session: Session, *, org_ids: list[int], today_key: str) -> int:
    threshold = _low_stock_threshold()
    if not org_ids:
        return 0
    rows = session.execute(
        select(Inventory).where(
            Inventory.organization_id.is_not(None),
            Inventory.organization_id.in_(org_ids),
            Inventory.quantity <= threshold,
        )
    ).scalars().all()
    created = 0
    for inv in rows:
        oid = int(inv.organization_id)  # type: ignore[arg-type]
        loc = f" @ {inv.location}" if inv.location else ""
        dedupe = f"low_stock:inventory:{inv.id}:{today_key}"
        body = (
            f"SKU **{inv.sku_name}**{loc} is at or below the low-stock threshold "
            f"(quantity **{inv.quantity}**, threshold **{threshold}**)."
        )
        payload: dict[str, Any] = {
            "sku_name": inv.sku_name,
            "location": inv.location or "",
            "quantity": str(inv.quantity),
            "threshold": str(threshold),
        }
        stmt = insert(Notification).values(
            organization_id=oid,
            kind="low_stock",
            severity="warning",
            title=f"Low stock: {inv.sku_name}",
            body=body,
            reference_type="inventory",
            reference_id=int(inv.id),
            payload=payload,
            dedupe_key=dedupe,
        )
        stmt = stmt.on_conflict_do_nothing(constraint=NOTIFICATION_CONSTRAINT)
        res = session.execute(stmt)
        if res.rowcount:
            created += 1
    return created


def _notify_overdue_debts(session: Session, *, org_ids: list[int], today_key: str) -> int:
    today = _today_utc()
    if not org_ids:
        return 0
    rows = session.execute(
        select(Debt).where(
            Debt.organization_id.is_not(None),
            Debt.organization_id.in_(org_ids),
            Debt.due_date.is_not(None),
            Debt.due_date < today,
        )
    ).scalars().all()
    created = 0
    for debt in rows:
        oid = int(debt.organization_id)  # type: ignore[arg-type]
        due = debt.due_date.isoformat() if debt.due_date else ""
        dedupe = f"debt_overdue:debt:{debt.id}:{today_key}"
        body = (
            f"Obligation to **{debt.lender_name}** was due **{due}** "
            f"(principal **{debt.principal}** INR, category **{debt.category_enum.value}**)."
        )
        payload: dict[str, Any] = {
            "lender_name": debt.lender_name,
            "principal": str(debt.principal),
            "due_date": due,
            "category": debt.category_enum.value,
        }
        stmt = insert(Notification).values(
            organization_id=oid,
            kind="debt_overdue",
            severity="warning",
            title=f"Overdue payment: {debt.lender_name}",
            body=body,
            reference_type="debt",
            reference_id=int(debt.id),
            payload=payload,
            dedupe_key=dedupe,
        )
        stmt = stmt.on_conflict_do_nothing(constraint=NOTIFICATION_CONSTRAINT)
        res = session.execute(stmt)
        if res.rowcount:
            created += 1
    return created


def run_alert_scan() -> None:
    """Single scan: all active orgs; insert notifications with dedupe (one row per kind/entity/day)."""
    global _alert_scan_suppress_until

    try:
        from services.worker_heartbeat import touch_heartbeat

        touch_heartbeat("alert_worker")
    except Exception:
        pass

    rid = new_request_id()
    now = time.time()
    if now < _alert_scan_suppress_until:
        log_event(
            rid,
            "alert_system.scan_skipped",
            ok=True,
            extra={
                "reason": "exponential_backoff",
                "suppress_until_epoch": _alert_scan_suppress_until,
            },
        )
        return

    if not _alert_circuit.can_execute():
        log_event(
            rid,
            "alert_system.circuit_open",
            ok=False,
            extra={
                "circuit_state": _alert_circuit.state.value,
                "seconds_until_half_open": round(_alert_circuit.seconds_until_half_open(), 2),
            },
        )
        return

    factory = get_session_factory()
    if factory is None:
        log_event(
            rid,
            "alert_system.skip",
            ok=False,
            extra={"reason": "DATABASE_URL missing or engine unavailable"},
        )
        return

    today_key = _today_utc().isoformat()
    t0 = time.perf_counter()
    orgs_scanned = 0
    alerts_sent = 0
    n_low = n_debt = n_factory = 0
    try:
        with session_scope() as session:
            org_ids = active_organization_ids(session)
            orgs_scanned = len(org_ids)
            if not org_ids:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                _alert_circuit.record_success()
                _alert_backoff_instance().reset()
                _alert_health.record_success()
                _log.info(
                    json.dumps(
                        {
                            "event": "alert.scan_complete",
                            "duration_ms": round(duration_ms, 2),
                            "orgs_scanned": 0,
                            "alerts_sent": 0,
                            "note": "no_active_orgs",
                        },
                        separators=(",", ":"),
                    )
                )
                log_event(
                    rid,
                    "alert_system.scan",
                    ok=True,
                    extra={"active_organizations": 0, "note": "no_active_orgs"},
                )
                return
            n_low = _notify_low_stock(session, org_ids=org_ids, today_key=today_key)
            n_debt = _notify_overdue_debts(session, org_ids=org_ids, today_key=today_key)
            n_factory = 0
            try:
                from services.project_engine import scan_stage2_failures_for_alerts

                n_factory = scan_stage2_failures_for_alerts(
                    session, org_ids=org_ids, today_key=today_key
                )
            except Exception as exc:
                _log.warning("alert_system.factory_stage2_scan_skipped: %s", exc)
            alerts_sent = int(n_low + n_debt + n_factory)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        _alert_circuit.record_success()
        _alert_backoff_instance().reset()
        _alert_health.record_success()
        _alert_scan_suppress_until = 0.0
        _log.info(
            json.dumps(
                {
                    "event": "alert.scan_complete",
                    "duration_ms": round(duration_ms, 2),
                    "orgs_scanned": orgs_scanned,
                    "alerts_sent": alerts_sent,
                    "healthy": _alert_health.is_healthy(),
                },
                separators=(",", ":"),
            )
        )
        log_event(
            rid,
            "alert_system.scan",
            ok=True,
            extra={
                "active_organizations": orgs_scanned,
                "notifications_low_stock": n_low,
                "notifications_debt_overdue": n_debt,
                "notifications_factory_stage2": n_factory,
            },
        )
    except Exception as exc:
        _log.exception("alert_system.scan_failed")
        log_event(rid, "alert_system.scan", ok=False, error=str(exc))
        _alert_circuit.record_failure()
        _alert_health.record_failure(str(exc))
        bo = _alert_backoff_instance()
        delay = bo.next_sleep()
        _alert_scan_suppress_until = time.time() + delay


def start_alert_scheduler() -> BackgroundScheduler | None:
    """
    Start background interval job. No-op if scheduler already running or DB unavailable.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if get_session_factory() is None:
        _log.warning("alert_system: DATABASE_URL not set; scheduler not started")
        return None

    sched = BackgroundScheduler(timezone="UTC")
    minutes = _interval_minutes()
    sched.add_job(
        run_alert_scan,
        IntervalTrigger(minutes=minutes),
        id="thiramai_alert_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    try:
        from workers.jarvis_email import (
            jarvis_email_poll_enabled,
            jarvis_poll_interval_minutes,
            run_jarvis_email_scan,
        )

        if jarvis_email_poll_enabled():
            jm = jarvis_poll_interval_minutes()
            sched.add_job(
                run_jarvis_email_scan,
                IntervalTrigger(minutes=jm),
                id="thiramai_jarvis_email",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            log_event(
                new_request_id(),
                "alert_system.jarvis_email_scheduled",
                ok=True,
                extra={"interval_minutes": jm},
            )
    except Exception as exc:
        _log.warning("alert_system.jarvis_email_schedule_skipped: %s", exc)

    try:
        from workers.alert_worker import automation_worker_enabled, register_automation_job

        if automation_worker_enabled():
            register_automation_job(sched)
    except Exception as exc:
        _log.warning("alert_system.automation_schedule_skipped: %s", exc)

    try:
        from workers.autonomy_worker import autonomy_engine_enabled, register_autonomy_job

        if autonomy_engine_enabled():
            register_autonomy_job(sched)
    except Exception as exc:
        _log.warning("alert_system.autonomy_schedule_skipped: %s", exc)

    try:
        from services.personal_meeting_intelligence import register_meeting_reminder_job

        register_meeting_reminder_job(sched)
    except Exception as exc:
        _log.warning("alert_system.meeting_reminders_skipped: %s", exc)

    try:
        from services.web_push_service import register_web_push_jobs

        register_web_push_jobs(sched)
    except Exception as exc:
        _log.warning("alert_system.web_push_jobs_skipped: %s", exc)

    sched.start()
    _scheduler = sched
    rid = new_request_id()
    log_event(
        rid,
        "alert_system.scheduler_started",
        ok=True,
        extra={"interval_minutes": minutes},
    )
    return sched


def list_active_alerts_for_organization(*, organization_id: int, limit: int = 100) -> dict[str, Any]:
    """
    Unread tenant notifications (``read_at`` IS NULL) for dashboards / Control Tower.

    Rows are created by the alert scheduler (low stock, overdue debt, etc.).
    """
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {
            "ok": False,
            "reason": "DATABASE_URL not configured",
            "organization_id": oid,
            "unread_count": 0,
            "items": [],
        }
    try:
        with factory() as session:
            stmt = (
                select(Notification)
                .where(
                    Notification.organization_id == oid,
                    Notification.read_at.is_(None),
                )
                .order_by(Notification.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
            rows = session.scalars(stmt).all()
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "organization_id": oid,
            "unread_count": 0,
            "items": [],
        }

    items: list[dict[str, Any]] = []
    for n in rows:
        items.append(
            {
                "id": int(n.id),
                "kind": n.kind,
                "severity": n.severity,
                "title": n.title,
                "body": (n.body[:800] + "…") if len(n.body) > 800 else n.body,
                "created_at_utc": n.created_at.isoformat() if n.created_at else None,
                "reference_type": n.reference_type,
                "reference_id": int(n.reference_id) if n.reference_id is not None else None,
                "dedupe_key": n.dedupe_key,
            }
        )
    return {
        "ok": True,
        "organization_id": oid,
        "unread_count": len(items),
        "items": items,
    }


def shutdown_alert_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    log_event(new_request_id(), "alert_system.scheduler_stopped", ok=True)


def main() -> None:
    """Standalone worker: APScheduler + blocking sleep (Ctrl+C to stop)."""
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(".") / ".env", override=False)
    ensure_thiramai_logging()
    start_alert_scheduler()
    run_alert_scan()
    try:
        from workers.jarvis_email import jarvis_email_poll_enabled, run_jarvis_email_scan

        if jarvis_email_poll_enabled():
            run_jarvis_email_scan()
    except Exception:
        pass
    try:
        from services.personal_meeting_intelligence import run_meeting_reminder_scan

        run_meeting_reminder_scan()
    except Exception:
        pass
    try:
        from services.web_push_service import run_daily_brief_web_push_scan, run_emi_web_push_scan

        run_emi_web_push_scan()
        run_daily_brief_web_push_scan()
    except Exception:
        pass
    try:
        while True:
            try:
                from services.worker_heartbeat import touch_heartbeat

                touch_heartbeat("alert_worker")
            except Exception:
                pass
            time.sleep(60)
    except KeyboardInterrupt:
        shutdown_alert_scheduler()


if __name__ == "__main__":
    main()
