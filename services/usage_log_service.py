"""
Product usage logging (usage_logs) and org-level analytics summary.

Best-effort inserts: failures never break primary request flows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import distinct, func, select

from core.database import get_session_factory
from core.db.models import AiDecision, UsageLog

_log = logging.getLogger("thiramai")

# Canonical action names (also accept client POST /analytics/usage-event)
ACTION_LOGIN = "login"
ACTION_SIGNUP = "signup"
ACTION_ONBOARDING_COMPLETE = "onboarding_complete"
ACTION_AI_DECISION_PENDING = "ai_decision_pending"
ACTION_AI_DECISION_EXECUTED = "ai_decision_executed"
ACTION_AI_DECISION_FAILED = "ai_decision_failed"
ACTION_AI_DECISION_APPROVED = "ai_decision_approved"
ACTION_AI_DECISION_REJECTED = "ai_decision_rejected"
ACTION_AI_DECISION_RESOLVE_FAILED = "ai_decision_resolve_failed"
ACTION_INVENTORY_CREATE = "inventory_create"
ACTION_INVENTORY_UPDATE = "inventory_update"
ACTION_INVOICE_CREATE = "invoice_create"
ACTION_API_ERROR = "api_error"


def log_usage_sync(
    *,
    organization_id: int,
    user_id: int | None,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert one usage row; swallow errors."""
    oid = int(organization_id)
    act = (action or "")[:128].strip()
    if not act:
        return
    try:
        factory = get_session_factory()
        if factory is None:
            return
        uid = int(user_id) if user_id is not None and int(user_id) > 0 else None
        with factory() as session:
            with session.begin():
                row = UsageLog(
                    organization_id=oid,
                    user_id=uid,
                    action=act,
                    event_metadata=metadata or None,
                )
                session.add(row)
    except Exception:
        _log.exception("usage_log_insert_failed", extra={"action": act, "org_id": oid})


def build_analytics_summary_sync(
    organization_id: int,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """Aggregates usage_logs + AiDecision counts + revenue snapshot + active alerts."""
    oid = int(organization_id)
    d = max(1, min(int(days), 366))
    since = datetime.now(timezone.utc) - timedelta(days=d)

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    with factory() as session:
        active_users_login = session.scalar(
            select(func.count(distinct(UsageLog.user_id))).where(
                UsageLog.organization_id == oid,
                UsageLog.created_at >= since,
                UsageLog.action == ACTION_LOGIN,
                UsageLog.user_id.isnot(None),
            )
        )
        active_users_any = session.scalar(
            select(func.count(distinct(UsageLog.user_id))).where(
                UsageLog.organization_id == oid,
                UsageLog.created_at >= since,
                UsageLog.user_id.isnot(None),
            )
        )
        total_events = session.scalar(
            select(func.count()).select_from(UsageLog).where(
                UsageLog.organization_id == oid,
                UsageLog.created_at >= since,
            )
        )
        stmt = (
            select(UsageLog.action, func.count())
            .where(
                UsageLog.organization_id == oid,
                UsageLog.created_at >= since,
            )
            .group_by(UsageLog.action)
        )
        by_action = {str(row[0]): int(row[1]) for row in session.execute(stmt).all()}

        ad_total = session.scalar(
            select(func.count()).select_from(AiDecision).where(AiDecision.organization_id == oid)
        )
        ad_pending = session.scalar(
            select(func.count()).select_from(AiDecision).where(
                AiDecision.organization_id == oid,
                AiDecision.status == "pending",
            )
        )
        ad_failed = session.scalar(
            select(func.count()).select_from(AiDecision).where(
                AiDecision.organization_id == oid,
                AiDecision.status == "failed",
            )
        )

    revenue_summary: dict[str, Any] = {}
    try:
        from services.analytics_service import compute_dashboard_summary_sync

        rev = compute_dashboard_summary_sync(oid, low_stock_threshold=5)
        if rev.get("ok"):
            revenue_summary = {
                "revenue_inr": rev.get("revenue_inr"),
                "gst_collected_inr": rev.get("gst_collected_inr"),
            }
        else:
            revenue_summary = {"ok": False, "error": rev.get("error")}
    except Exception as exc:
        revenue_summary = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    alerts_block: dict[str, Any] = {}
    try:
        from workers import alert_system

        alerts_block = alert_system.list_active_alerts_for_organization(organization_id=oid, limit=200)
    except Exception as exc:
        alerts_block = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    unread = 0
    if isinstance(alerts_block, dict) and alerts_block.get("ok") is not False:
        unread = int(alerts_block.get("unread_count") or 0)

    return {
        "ok": True,
        "schema": "thiramai.analytics.summary.v1",
        "organization_id": oid,
        "window_days": d,
        "since_utc": since.isoformat(),
        "active_users_distinct_login": int(active_users_login or 0),
        "active_users_distinct_any_event": int(active_users_any or 0),
        "usage_events_total": int(total_events or 0),
        "usage_events_by_action": by_action,
        "ai_decisions": {
            "total": int(ad_total or 0),
            "pending": int(ad_pending or 0),
            "failed": int(ad_failed or 0),
        },
        "revenue_summary": revenue_summary,
        "alerts": alerts_block,
        "alerts_unread_count": unread,
    }
