"""
Upgrade 2.3 — event-driven Jarvis: durable queue + immediate dispatch hooks.

PostgreSQL may also insert rows via DB triggers (see migration ``0042``).
Application hooks call ``enqueue_and_flush_sync`` so API paths react without waiting for the drain worker.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import JarvisAgentEventQueue, UserOrganizationMembership

_log = logging.getLogger("thiramai.jarvis_agent_event_engine")


def clear_agent_cycle_rate_limit_for_user(user_id: int) -> None:
    """Allow an immediate ``run_agent_cycle_sync`` after a high-priority business event."""
    try:
        import services.jarvis_autonomous_agent as ja

        ja._LAST_CYCLE_TS.pop(int(user_id), None)
    except Exception as exc:
        _log.debug("clear rate limit: %s", exc)


def enqueue_agent_event_sync(
    *,
    organization_id: int | None,
    user_id: int | None,
    event_type: str,
    payload: dict[str, Any],
    priority: int = 5,
) -> dict[str, Any]:
    oid = int(organization_id) if organization_id and int(organization_id) > 0 else None
    uid = int(user_id) if user_id and int(user_id) > 0 else None
    et = (event_type or "").strip()[:64]
    if not et:
        return {"ok": False, "error": "event_type required"}
    pl = payload if isinstance(payload, dict) else {}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        with session.begin():
            row = JarvisAgentEventQueue(
                organization_id=oid,
                user_id=uid,
                event_type=et,
                payload=pl,
                priority=max(0, min(99, int(priority))),
            )
            session.add(row)
            session.flush()
            eid = int(row.id)
    return {"ok": True, "event_id": eid}


def _member_user_ids_for_org(organization_id: int, *, limit: int = 8) -> list[int]:
    oid = int(organization_id)
    if oid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    with factory() as session:
        return [
            int(x)
            for x in session.scalars(
                select(UserOrganizationMembership.user_id).where(
                    UserOrganizationMembership.organization_id == oid,
                    UserOrganizationMembership.is_active.is_(True),
                ).limit(limit)
            ).all()
        ]


def process_agent_event_sync(*, event_id: int) -> dict[str, Any]:
    """Run Jarvis reactions for one queue row, then mark processed on success."""
    eid = int(event_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        row = session.get(JarvisAgentEventQueue, eid)
        if row is None:
            return {"ok": False, "error": "event not found"}
        if row.processed_at is not None:
            return {"ok": True, "skipped": "already_processed", "event_id": eid}
        et = row.event_type
        pl = row.payload if isinstance(row.payload, dict) else {}
        oid = int(row.organization_id) if row.organization_id else 0
        uid_hint = int(row.user_id) if row.user_id else 0

    reacted: list[str] = []
    try:
        if et == "inventory_quantity_change" and oid > 0:
            sku = str(pl.get("sku_name") or "").strip()
            qty = pl.get("quantity")
            uids = _member_user_ids_for_org(oid)
            if uid_hint > 0 and uid_hint not in uids:
                uids = [uid_hint] + uids
            from services.jarvis_proactive_service import generate_morning_intelligence_sync
            from services.jarvis_autonomous_agent import run_agent_cycle_sync

            for uid in uids[:6]:
                clear_agent_cycle_rate_limit_for_user(uid)
                generate_morning_intelligence_sync(user_id=uid, organization_ids=[oid])
                run_agent_cycle_sync(user_id=uid, organization_ids=[oid])
                reacted.append(f"user={uid}")
        elif et == "personal_meeting_created" and oid > 0 and uid_hint > 0:
            from services.jarvis_proactive_events import notify_meeting_window

            clear_agent_cycle_rate_limit_for_user(uid_hint)
            notify_meeting_window(user_id=uid_hint, organization_ids=[oid])
            from services.jarvis_autonomous_agent import run_agent_cycle_sync

            run_agent_cycle_sync(user_id=uid_hint, organization_ids=[oid])
            reacted.append("meeting_realtime")
        elif et == "invoice_created" and oid > 0:
            from services.jarvis_proactive_service import generate_morning_intelligence_sync
            from services.jarvis_autonomous_agent import run_agent_cycle_sync

            for uid in _member_user_ids_for_org(oid)[:6]:
                clear_agent_cycle_rate_limit_for_user(uid)
                generate_morning_intelligence_sync(user_id=uid, organization_ids=[oid])
                run_agent_cycle_sync(user_id=uid, organization_ids=[oid])
                reacted.append(f"invoice_user={uid}")
        else:
            reacted.append("no_handler")
    except Exception as exc:
        _log.warning("process_agent_event_sync id=%s: %s", eid, exc)
        return {"ok": False, "error": str(exc), "event_id": eid}
    now = datetime.now(timezone.utc)
    with factory() as session:
        with session.begin():
            r2 = session.get(JarvisAgentEventQueue, eid)
            if r2 and r2.processed_at is None:
                r2.processed_at = now
    return {"ok": True, "event_id": eid, "reacted": reacted}


def enqueue_and_flush_sync(
    *,
    organization_id: int | None,
    user_id: int | None,
    event_type: str,
    payload: dict[str, Any],
    priority: int = 5,
) -> dict[str, Any]:
    """Insert queue row and process it immediately (Step 1 app-side trigger)."""
    out = enqueue_agent_event_sync(
        organization_id=organization_id,
        user_id=user_id,
        event_type=event_type,
        payload=payload,
        priority=priority,
    )
    if not out.get("ok"):
        return out
    return process_agent_event_sync(event_id=int(out["event_id"]))


def drain_agent_event_queue_sync(*, limit: int = 30) -> dict[str, Any]:
    """Worker: process oldest pending rows (e.g. from PostgreSQL triggers alone)."""
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    lim = max(1, min(int(limit), 100))
    with factory() as session:
        rows = list(
            session.scalars(
                select(JarvisAgentEventQueue)
                .where(JarvisAgentEventQueue.processed_at.is_(None))
                .order_by(JarvisAgentEventQueue.priority.desc(), JarvisAgentEventQueue.created_at.asc())
                .limit(lim)
            ).all()
        )
    done = 0
    for r in rows:
        pr = process_agent_event_sync(event_id=int(r.id))
        if pr.get("ok"):
            done += 1
    return {"ok": True, "processed": done, "candidates": len(rows)}


# --- Typed hooks (inventory / billing / meetings) ---


def record_inventory_quantity_event_sync(
    *,
    organization_id: int,
    inventory_item_id: int,
    sku_name: str,
    quantity: Any,
    reorder_point: Any = None,
    user_id: int | None = None,
) -> None:
    oid = int(organization_id)
    if oid <= 0:
        return
    pr = 9
    try:
        from decimal import Decimal

        q = Decimal(str(quantity))
        rp = Decimal(str(reorder_point)) if reorder_point is not None else Decimal("0")
        if rp > 0 and q > rp:
            pr = 4
    except Exception:
        pass
    try:
        enqueue_and_flush_sync(
            organization_id=oid,
            user_id=user_id,
            event_type="inventory_quantity_change",
            payload={
                "inventory_item_id": int(inventory_item_id),
                "sku_name": (sku_name or "").strip(),
                "quantity": quantity,
                "reorder_point": reorder_point,
            },
            priority=pr,
        )
    except Exception as exc:
        _log.debug("record_inventory_quantity_event_sync: %s", exc)


def record_invoice_created_event_sync(
    *,
    organization_id: int,
    invoice_id: int,
    invoice_no: str,
    grand_total_inr: float,
    user_id: int | None = None,
) -> None:
    try:
        enqueue_and_flush_sync(
            organization_id=int(organization_id),
            user_id=user_id,
            event_type="invoice_created",
            payload={
                "invoice_id": int(invoice_id),
                "invoice_no": (invoice_no or "")[:128],
                "grand_total_inr": float(grand_total_inr),
            },
            priority=5,
        )
    except Exception as exc:
        _log.debug("record_invoice_created_event_sync: %s", exc)


def record_meeting_created_event_sync(
    *,
    user_id: int,
    organization_id: int,
    meeting_id: int,
    title: str,
) -> None:
    try:
        enqueue_and_flush_sync(
            organization_id=int(organization_id),
            user_id=int(user_id),
            event_type="personal_meeting_created",
            payload={"meeting_id": int(meeting_id), "title": (title or "")[:500]},
            priority=6,
        )
    except Exception as exc:
        _log.debug("record_meeting_created_event_sync: %s", exc)
