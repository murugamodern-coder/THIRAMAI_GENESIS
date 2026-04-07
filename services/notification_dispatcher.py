"""
Daily briefing narrative + optional draft replies (Phase 5 Comms OS).

Pulls Business Snapshot, comms inbox tiers, and statutory compliance context.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import CommsInbox
from services.business_snapshot_service import build_business_snapshot
from services.compliance_service import summarize_compliance_for_briefing
from services.draft_reply_service import draft_reply_for_auditor_compliance, draft_reply_for_business_inquiry


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def _count_comms_since(
    session: Session,
    *,
    organization_id: int,
    since: datetime,
    tier: str,
) -> int:
    q = select(func.count()).select_from(CommsInbox).where(
        CommsInbox.organization_id == int(organization_id),
        CommsInbox.intelligence_tier == tier,
        CommsInbox.created_at >= since,
    )
    return int(session.execute(q).scalar_one() or 0)


def _latest_comms(
    session: Session,
    *,
    organization_id: int,
    tier: str | None,
    limit: int = 1,
) -> list[CommsInbox]:
    stmt = (
        select(CommsInbox)
        .where(CommsInbox.organization_id == int(organization_id))
        .order_by(CommsInbox.created_at.desc())
        .limit(max(1, min(limit, 20)))
    )
    if tier:
        stmt = stmt.where(CommsInbox.intelligence_tier == tier)
    return list(session.execute(stmt).scalars().all())


def build_daily_briefing(
    organization_id: int,
    *,
    low_stock_threshold: int = 5,
) -> dict[str, Any]:
    """
    Build a single briefing object with **narrative** (JARVIS-style) and optional **draft_reply** / **auditor_draft**.

    Does not send email — human approves sends.
    """
    oid = int(organization_id)
    now = datetime.now(timezone.utc)
    since24 = now - timedelta(hours=24)

    snap = build_business_snapshot(
        oid,
        low_stock_threshold=low_stock_threshold,
        _as_of=now,
        use_cache=False,
    )
    comp_lines = summarize_compliance_for_briefing(oid, today=now.date())

    factory = _factory()
    red_n = orange_n = yellow_n = 0
    latest_orange: CommsInbox | None = None
    latest_red: CommsInbox | None = None
    if factory is not None:
        with factory() as session:
            red_n = _count_comms_since(session, organization_id=oid, since=since24, tier="red")
            orange_n = _count_comms_since(session, organization_id=oid, since=since24, tier="orange")
            yellow_n = _count_comms_since(session, organization_id=oid, since=since24, tier="yellow")
            lo = _latest_comms(session, organization_id=oid, tier="orange", limit=1)
            lr = _latest_comms(session, organization_id=oid, tier="red", limit=1)
            if lo:
                latest_orange = lo[0]
            if lr:
                latest_red = lr[0]

    parts: list[str] = ["Sir,"]

    if red_n:
        parts.append(f"you have **{red_n}** urgent message(s) (🔴 Action Required) in the last 24h.")
    else:
        parts.append("no 🔴 **Action Required** emails logged in the last 24h.")

    if orange_n:
        parts.append(f"There are **{orange_n}** tax/compliance-tagged message(s) (🟠) to review.")
    else:
        parts.append("No new 🟠 **Tax/Compliance** messages in the last 24h.")

    if comp_lines:
        parts.append("Statutory watch: " + " ".join(comp_lines[:4]))
    else:
        parts.append("No statutory deadlines inside the 3-day warning window (or all marked filed).")

    snap_bit = ""
    if snap.get("ok"):
        pm = snap.get("profit_month") or {}
        snap_bit = f" Month net (management KPI) is around **₹{pm.get('net_profit_inr', 'n/a')}**."
    parts.append(snap_bit)

    draft_auditor = None
    if latest_orange:
        draft_auditor = draft_reply_for_auditor_compliance(
            subject_hint=latest_orange.subject,
            compliance_lines=comp_lines,
            business_snapshot=snap,
        )
        parts.append(
            " I have **drafted a reply** for the latest tax/compliance thread — review before sending."
        )

    draft_general = None
    if latest_red and not draft_auditor:
        draft_general = draft_reply_for_business_inquiry(
            business_snapshot=snap,
            sender_hint=latest_red.sender[:120],
            subject_hint=latest_red.subject[:200],
            thread_summary=latest_red.body_summary[:600],
        )
        parts.append(" I drafted a **business reply** for the latest urgent thread — confirm before send.")

    narrative = " ".join(parts).replace("  ", " ").strip()

    return {
        "ok": True,
        "organization_id": oid,
        "as_of_utc": now.isoformat(),
        "narrative": narrative,
        "counts_24h": {"red": red_n, "orange": orange_n, "yellow": yellow_n},
        "compliance_lines": comp_lines,
        "business_snapshot": snap,
        "draft_reply_auditor": draft_auditor,
        "draft_reply_business": draft_general,
    }
