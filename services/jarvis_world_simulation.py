"""
Upgrade 2.3 — world-model style projections (cash / risk) for candidate actions.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import InventoryItem


def simulate_future_state(action: dict[str, Any], *, days: int = 7) -> dict[str, Any]:
    """
    Step 3 — lightweight projection for ``days`` horizon (no Monte Carlo; transparent heuristics).

    ``action`` examples::

        {"kind": "reorder", "organization_id": 1, "sku": "Soap", "order_qty": 10, "unit_cost": 120}
        {"kind": "stock_trade", "symbol": "RELIANCE", "notional_inr": 50000}
    """
    d = max(1, min(int(days), 90))
    kind = str((action or {}).get("kind") or "").strip().lower()
    if kind == "reorder":
        oid = int(action.get("organization_id") or 0)
        sku = str(action.get("sku") or "").strip()
        q = action.get("order_qty")
        uc = action.get("unit_cost")
        try:
            qd = Decimal(str(q)) if q is not None else Decimal("1")
        except Exception:
            qd = Decimal("1")
        try:
            ucd = Decimal(str(uc)) if uc is not None else Decimal("0")
        except Exception:
            ucd = Decimal("0")
        if oid > 0 and sku and ucd <= 0:
            factory = get_session_factory()
            if factory is not None:
                with factory() as session:
                    row = session.execute(
                        select(InventoryItem)
                        .where(InventoryItem.organization_id == oid, InventoryItem.sku_name == sku)
                        .limit(1)
                    ).scalar_one_or_none()
                    if row and row.unit_cost_pre_tax is not None:
                        ucd = Decimal(str(row.unit_cost_pre_tax))
        cash_out = float((qd * ucd).quantize(Decimal("0.01")))
        horizon = (date.today() + timedelta(days=d)).isoformat()
        return {
            "ok": True,
            "horizon_days": d,
            "horizon_date": horizon,
            "projected_outcome": (
                f"Ordering ~{float(qd):g} units at ≈₹{float(ucd):,.2f} unit pre-tax implies "
                f"≈₹{cash_out:,.0f} cash tied up in draft PO over the next week (excl. GST / freight)."
            ),
            "cash_impact_inr_estimate": cash_out,
            "risk_notes": ["Supplier lead time not modeled — pad 3–5 buffer days if volatile."],
        }
    if kind in ("stock_trade", "equity_trade"):
        n = float(action.get("notional_inr") or 0)
        return {
            "ok": True,
            "horizon_days": d,
            "projected_outcome": "Paper portfolio risk band widens with new intraday exposure.",
            "risk_impact": "high" if n > 100_000 else "medium",
            "cash_impact_inr_estimate": 0.0,
            "risk_notes": ["Autonomous agent will not auto-execute trades (safety policy)."],
        }
    return {
        "ok": True,
        "horizon_days": d,
        "projected_outcome": "No specialized simulator for this action kind — review in Command Center.",
        "cash_impact_inr_estimate": None,
        "risk_notes": [],
    }
