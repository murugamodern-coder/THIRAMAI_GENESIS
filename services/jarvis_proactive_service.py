"""Morning intelligence: subsidies, stock, machines, EMIs, receivables → DB alerts + Today brief."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import (
    AgroSubsidyCase,
    Asset,
    Invoice,
    JarvisProactiveAlert,
    Payment,
    PersonalLoan,
    ProductionLog,
    UserOrganizationMembership,
)
from services.inventory_phase2_service import list_low_stock_alerts_sync
from services.stock_market_jarvis import morning_market_brief_sync

_log = logging.getLogger("thiramai.jarvis_proactive")


def _priority_score(p: str) -> int:
    return {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get((p or "").lower(), 4)


def _upsert_alert(
    session: Session,
    *,
    user_id: int,
    organization_id: int | None,
    alert_type: str,
    priority: str,
    message: str,
    action_text: str,
    dedupe_key: str,
    payload: dict[str, Any] | None = None,
) -> None:
    row = session.execute(
        select(JarvisProactiveAlert).where(
            JarvisProactiveAlert.user_id == int(user_id),
            JarvisProactiveAlert.dedupe_key == dedupe_key[:256],
        ).limit(1)
    ).scalar_one_or_none()
    pl = payload if isinstance(payload, dict) else {}
    if row:
        row.message = message[:8000]
        row.priority = priority[:16]
        row.action_text = (action_text or "")[:4000]
        row.payload = pl
        row.organization_id = organization_id
        return
    session.add(
        JarvisProactiveAlert(
            user_id=int(user_id),
            organization_id=organization_id,
            alert_type=alert_type[:64],
            priority=priority[:16],
            message=message[:8000],
            action_text=(action_text or "")[:4000],
            payload=pl,
            dedupe_key=dedupe_key[:256],
        )
    )


def generate_morning_intelligence_sync(*, user_id: int, organization_ids: list[int]) -> dict[str, Any]:
    """
    Build alerts for one user across their orgs (typically JWT org + optional same-day scan).
    Persists rows (deduped by dedupe_key per user).
    """
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    oids = [int(x) for x in organization_ids if int(x) > 0]
    if not oids:
        return {"ok": False, "error": "organization_ids required"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}

    today = datetime.now(timezone.utc).date()
    cutoff_subsidy_dt = datetime.now(timezone.utc) - timedelta(days=45)
    cutoff_idle = datetime.now(timezone.utc) - timedelta(days=7)
    cutoff_inv = today - timedelta(days=30)

    alerts_in_memory: list[dict[str, Any]] = []

    with factory() as session:
        with session.begin():
            for oid in oids:
                # Stale subsidy applications
                rows = session.scalars(
                    select(AgroSubsidyCase)
                    .where(AgroSubsidyCase.organization_id == oid)
                    .where(AgroSubsidyCase.created_at < cutoff_subsidy_dt)
                    .where(
                        AgroSubsidyCase.application_status.notin_(("received", "rejected", "closed", "paid"))
                    )
                    .limit(20)
                ).all()
                low_alerts = list_low_stock_alerts_sync(organization_id=oid, threshold_override=5.0)
                for it in (low_alerts.get("alerts") or [])[:8]:
                    if not isinstance(it, dict):
                        continue
                    sku = str(it.get("sku_name") or "Item").strip()
                    qty = it.get("quantity")
                    msg = f"{sku} is low stock (qty {qty}) — reorder soon."
                    dk = f"lowstock:{oid}:{sku[:80]}"
                    _upsert_alert(
                        session,
                        user_id=uid,
                        organization_id=oid,
                        alert_type="reorder",
                        priority="urgent",
                        message=msg,
                        action_text="Create purchase order / call supplier",
                        dedupe_key=dk,
                        payload={"sku": sku},
                    )
                    alerts_in_memory.append({"type": "reorder", "priority": "urgent", "message": msg})

                for r in rows:
                    days = (today - r.created_at.date()).days if r.created_at else 0
                    msg = f"Subsidy for {r.farmer_name} ({r.scheme_name}) pending ~{days} days — follow up with agriculture office."
                    dk = f"subsidy:{oid}:{r.id}"
                    _upsert_alert(
                        session,
                        user_id=uid,
                        organization_id=oid,
                        alert_type="follow_up",
                        priority="high",
                        message=msg,
                        action="Call district agriculture helpdesk / visit office",
                        dedupe_key=dk,
                        payload={"farmer_id": int(r.id), "scheme": r.scheme_name},
                    )
                    alerts_in_memory.append({"type": "follow_up", "priority": "high", "message": msg})

                # Idle assets (no production log in 7d)
                assets = session.scalars(select(Asset).where(Asset.organization_id == oid).limit(200)).all()
                for a in assets:
                    last_ts = session.execute(
                        select(func.max(ProductionLog.timestamp)).where(ProductionLog.asset_id == int(a.id))
                    ).scalar()
                    if last_ts is None or last_ts < cutoff_idle:
                        idle_days = (
                            (datetime.now(timezone.utc) - last_ts).days
                            if last_ts
                            else 999
                        )
                        msg = f"Machine/asset '{a.name}' has no production logged recently (~{idle_days}d) — plan a batch."
                        dk = f"idle:{oid}:{a.id}"
                        _upsert_alert(
                            session,
                            user_id=uid,
                            organization_id=oid,
                            alert_type="production",
                            priority="medium",
                            message=msg,
                            action_text="Create production task / log output in Business OS",
                            dedupe_key=dk,
                            payload={"asset_id": int(a.id)},
                        )
                        alerts_in_memory.append({"type": "production", "priority": "medium", "message": msg})

                # Overdue unpaid invoices (by invoice_date)
                invs = session.scalars(
                    select(Invoice)
                    .where(
                        Invoice.organization_id == oid,
                        Invoice.payment_status != "paid",
                        Invoice.invoice_date.isnot(None),
                        Invoice.invoice_date <= cutoff_inv,
                    )
                    .limit(25)
                ).all()
                for inv in invs:
                    paid = session.execute(
                        select(func.coalesce(func.sum(Payment.amount_inr), 0)).where(Payment.invoice_id == int(inv.id))
                    ).scalar() or Decimal("0")
                    due = Decimal(str(inv.grand_total_inr or 0)) - Decimal(str(paid))
                    if due <= Decimal("0.01"):
                        continue
                    overdue_days = (today - inv.invoice_date).days if inv.invoice_date else 0
                    cref = (inv.external_ref or "")[:120]
                    msg = f"Invoice #{inv.invoice_no} ₹{float(due):,.0f} overdue ~{overdue_days}d — ref {cref or 'n/a'}."
                    dk = f"overdue_inv:{oid}:{inv.id}"
                    _upsert_alert(
                        session,
                        user_id=uid,
                        organization_id=oid,
                        alert_type="collection",
                        priority="high",
                        message=msg,
                        action_text="Call customer / send payment reminder",
                        dedupe_key=dk,
                        payload={"invoice_id": int(inv.id)},
                    )
                    alerts_in_memory.append({"type": "collection", "priority": "high", "message": msg})

            # EMIs due within 3 days (personal loans — user scoped)
            horizon = today + timedelta(days=3)
            loans = session.scalars(
                select(PersonalLoan).where(PersonalLoan.user_id == uid, PersonalLoan.is_closed.is_(False)).limit(50)
            ).all()
            for ln in loans:
                nd = ln.next_due_date
                if nd is None or nd < today or nd > horizon:
                    continue
                days_until = (nd - today).days
                amt = str(ln.emi_amount or "0")
                name = (ln.display_name or "Loan").strip()
                msg = f"EMI ₹{amt} due in {days_until} day(s) — {name}."
                dk = f"emi:{uid}:{nd.isoformat()}:{name[:40]}"
                _upsert_alert(
                    session,
                    user_id=uid,
                    organization_id=None,
                    alert_type="payment",
                    priority="urgent",
                    message=msg,
                    action_text="Transfer funds before due date",
                    dedupe_key=dk,
                    payload={"loan_id": int(ln.id)},
                )
                alerts_in_memory.append({"type": "payment", "priority": "urgent", "message": msg})

    alerts_in_memory.sort(key=lambda a: _priority_score(str(a.get("priority"))))
    return {"ok": True, "alerts_count": len(alerts_in_memory), "alerts": alerts_in_memory[:50]}


def list_recent_proactive_for_brief_sync(*, user_id: int, limit: int = 12) -> list[dict[str, Any]]:
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 40))
    since = datetime.now(timezone.utc) - timedelta(days=3)
    with factory() as session:
        rows = list(
            session.scalars(
                select(JarvisProactiveAlert)
                .where(JarvisProactiveAlert.user_id == uid, JarvisProactiveAlert.created_at >= since)
                .order_by(JarvisProactiveAlert.created_at.desc())
                .limit(lim * 2)
            ).all()
        )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        key = f"{r.alert_type}:{r.message[:80]}"
        if key in seen:
            continue
        seen.add(key)
        sev = "high" if r.priority in ("urgent", "high") else "medium" if r.priority == "medium" else "low"
        out.append(
            {
                "code": r.alert_type,
                "severity": sev,
                "type": r.alert_type,
                "priority": r.priority,
                "message": r.message,
                "action": r.action_text,
                "organization_id": int(r.organization_id) if r.organization_id else None,
            }
        )
        if len(out) >= lim:
            break
    return out


def run_morning_job_all_users_sync() -> dict[str, Any]:
    """Scheduler entry: all active users with at least one membership."""
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no database"}
    processed = 0
    with factory() as session:
        user_ids = list(
            session.scalars(
                select(UserOrganizationMembership.user_id)
                .where(UserOrganizationMembership.is_active.is_(True))
                .distinct()
            ).all()
        )
    for uid in user_ids:
        uid = int(uid)
        if uid <= 0:
            continue
        with factory() as s2:
            oids = [
                int(x)
                for x in s2.scalars(
                    select(UserOrganizationMembership.organization_id).where(
                        UserOrganizationMembership.user_id == uid,
                        UserOrganizationMembership.is_active.is_(True),
                    )
                ).all()
            ]
        if not oids:
            continue
        try:
            generate_morning_intelligence_sync(user_id=uid, organization_ids=oids[:5])
            processed += 1
        except Exception as exc:
            _log.warning("proactive user=%s failed: %s", uid, exc)
    return {"ok": True, "users_processed": processed}


def attach_market_brief_to_payload(payload: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    """Merge compact market snapshot into an existing dict (e.g. today brief)."""
    from core.database import get_session_factory as _gf
    from core.db.models import StockWatchlistEntry as SW

    syms: list[str] = []
    fac = _gf()
    if fac is not None and int(user_id) > 0:
        with fac() as session:
            rows = session.scalars(
                select(SW.symbol).where(SW.user_id == int(user_id)).limit(12)
            ).all()
            syms = [str(x) for x in rows if x]
    if not syms:
        syms = ["RELIANCE", "TCS", "INFY"]
    try:
        payload["jarvis_market_brief"] = morning_market_brief_sync(watchlist_symbols=syms)
    except Exception as exc:
        payload["jarvis_market_brief"] = {"ok": False, "error": str(exc)}
    return payload
