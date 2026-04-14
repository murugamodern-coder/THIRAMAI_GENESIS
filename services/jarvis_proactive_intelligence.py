"""
Upgrade 2.1 — Intelligence layer: dependency chain, weighted scoring, memory-aware modifiers.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from core.database import get_session_factory
from core.db.models import InventoryItem, JarvisProactiveFeedback, JarvisFact, Supplier

_log = logging.getLogger("thiramai.jarvis_proactive_intelligence")

# Weighted priority (Step 1): sum of weighted normalized subscores → higher = more important
W_IMPACT = float((os.getenv("THIRAMAI_PROACTIVE_W_IMPACT") or "0.45").strip())
W_URGENCY = float((os.getenv("THIRAMAI_PROACTIVE_W_URGENCY") or "0.35").strip())
W_CONFIDENCE = float((os.getenv("THIRAMAI_PROACTIVE_W_CONFIDENCE") or "0.20").strip())


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def compute_weighted_priority_score(*, impact: float, urgency: float, confidence: float) -> float:
    """Returns 0–100 style score (higher = more important)."""
    return 100.0 * (
        W_IMPACT * _clamp01(impact) + W_URGENCY * _clamp01(urgency) + W_CONFIDENCE * _clamp01(confidence)
    )


def count_recent_outcomes_sync(*, user_id: int, alert_type: str, outcome: str, days: int = 14) -> int:
    uid = int(user_id)
    if uid <= 0:
        return 0
    factory = get_session_factory()
    if factory is None:
        return 0
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))
    at = (alert_type or "").strip()[:64]
    oc = (outcome or "").strip().lower()[:32]
    with factory() as session:
        n = session.scalar(
            select(func.count())
            .select_from(JarvisProactiveFeedback)
            .where(
                JarvisProactiveFeedback.user_id == uid,
                JarvisProactiveFeedback.alert_type == at,
                JarvisProactiveFeedback.outcome == oc,
                JarvisProactiveFeedback.created_at >= since,
            )
        )
    return int(n or 0)


def feedback_confidence_multiplier(*, user_id: int, alert_type: str) -> float:
    """Reduce confidence when user repeatedly ignores similar alerts."""
    ignored = count_recent_outcomes_sync(user_id=user_id, alert_type=alert_type, outcome="ignored", days=14)
    acted = count_recent_outcomes_sync(user_id=user_id, alert_type=alert_type, outcome="acted", days=14)
    noise = max(0, min(5, ignored)) * 0.08
    trust = min(3, acted) * 0.05
    return max(0.25, min(1.0, 1.0 - noise + trust))


def feedback_priority_noise_multiplier(*, user_id: int, alert_type: str) -> float:
    """
    Down-weight surfaced priority when the user consistently ignores a class of alert (learning loop).
    Stronger than confidence-only so equity / risk noise drops visibly.
    """
    ignored = count_recent_outcomes_sync(user_id=user_id, alert_type=alert_type, outcome="ignored", days=14)
    n = int(ignored or 0)
    if n >= 8:
        return 0.5
    if n >= 5:
        return 0.65
    if n >= 3:
        return 0.8
    return 1.0


def fetch_memory_snippets_sync(*, user_id: int) -> dict[str, Any]:
    """Lightweight preferences / facts for alert personalization."""
    uid = int(user_id)
    out: dict[str, Any] = {"facts": [], "cash_stress": False, "prefers_upi": False}
    if uid <= 0:
        return out
    factory = get_session_factory()
    if factory is None:
        return out
    with factory() as session:
        rows = list(
            session.scalars(
                select(JarvisFact)
                .where(JarvisFact.user_id == uid)
                .order_by(JarvisFact.created_at.desc())
                .limit(24)
            ).all()
        )
    for r in rows:
        k = (r.key or "").lower()
        v = (r.value or "").lower()
        out["facts"].append({"type": r.fact_type, "key": r.key, "value": r.value})
        if "cash" in k or "bank" in k or "balance" in k:
            if any(x in v for x in ("low", "tight", "short")):
                out["cash_stress"] = True
        if "upi" in v or "upi" in k:
            out["prefers_upi"] = True
    return out


def analyze_dependencies(
    *,
    alert_type: str,
    organization_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Step 6 — multi-step dependency sketch (read-only).

    Example chain: low stock → supplier → unit economics → recommendation.
    """
    at = (alert_type or "").strip().lower()
    oid = int(organization_id)
    pl = payload if isinstance(payload, dict) else {}
    chain: list[str] = []
    recommendation = "Review in Command Center."
    supplier_hint: dict[str, Any] | None = None
    budget_note = ""

    if at == "reorder" and oid > 0:
        sku = str(pl.get("sku") or pl.get("sku_name") or "").strip()
        chain.append(f"SKU «{sku}» is below comfortable stock.")
        factory = get_session_factory()
        if factory is None:
            return {"chain": chain, "recommendation": recommendation, "supplier": None, "budget_note": ""}
        with factory() as session:
            sup = session.execute(
                select(Supplier).where(Supplier.organization_id == oid).order_by(Supplier.name.asc()).limit(1)
            ).scalar_one_or_none()
            if sup:
                supplier_hint = {"id": int(sup.id), "name": sup.name}
                chain.append(f"Primary supplier candidate: {sup.name} (id {sup.id}).")
            if sku:
                row = session.execute(
                    select(InventoryItem)
                    .where(InventoryItem.organization_id == oid, InventoryItem.sku_name == sku)
                    .limit(1)
                ).scalar_one_or_none()
                if row:
                    uc = row.unit_cost_pre_tax
                    q = row.quantity
                    chain.append(f"Current on-hand qty ≈ {q}; unit cost pre-tax ≈ ₹{uc or 0}.")
                    if uc and row.reorder_point:
                        budget_note = (
                            f"Estimated reorder line value ≈ ₹{float(uc) * max(1, float(row.reorder_point)):.0f} "
                            "(rough)."
                        )
                        chain.append(budget_note)
            recommendation = (
                "Create a **draft** purchase order for approval, or call the supplier for expedited delivery."
            )

    elif at == "payment":
        chain.append("EMI / loan payment window is near.")
        recommendation = "Move funds early if cash is tight; avoid last-day UPI caps."
    elif at == "meeting_soon":
        mid = pl.get("meeting_id")
        mins = pl.get("minutes_until")
        chain.append(f"Meeting ({mid}) starts in ~{mins} minutes — calendar-critical path.")
        recommendation = "Open join link early; hand off driving if needed."
    elif at in ("equity_risk", "stock_signal", "watchlist_move"):
        chain.append("Portfolio / market signal affects daily risk budget.")
        recommendation = "Pause new intraday risk until P&L resets; collect receivables if cash overlap."
    else:
        chain.append(f"Alert type «{at}» — default triage.")

    return {
        "chain": chain,
        "recommendation": recommendation,
        "supplier": supplier_hint,
        "budget_note": budget_note,
    }


def apply_memory_to_scores(
    *,
    memory: dict[str, Any],
    alert_type: str,
    impact: float,
    urgency: float,
    confidence: float,
) -> tuple[float, float, float, str]:
    """Step 3 — tweak scores + return a short memory note for reasoning."""
    notes: list[str] = []
    if memory.get("cash_stress") and alert_type in ("payment", "reorder", "collection"):
        urgency = min(1.0, urgency + 0.15)
        notes.append("Memory: cash flagged as tight — urgency boosted.")
    if memory.get("prefers_upi") and alert_type == "payment":
        notes.append("Memory: user prefers UPI flows — mention UPI in action copy.")
    if alert_type == "reorder" and not memory.get("cash_stress"):
        confidence = min(1.0, confidence + 0.05)
        notes.append("Memory: no recent cash stress — slightly higher confidence on reorder.")
    return impact, urgency, confidence, " ".join(notes).strip()
