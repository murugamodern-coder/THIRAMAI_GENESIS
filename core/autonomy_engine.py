"""
Safe autonomy: evaluate tenant/system signals and emit **suggestions only**.

Callers must not execute these blindly. Controlled execution belongs in
``core.orchestrator_brain`` when ``context["auto_mode"]`` is true and the trigger
is a **system** event (never for silent financial sells).
"""

from __future__ import annotations

import os
from typing import Any


def evaluate_autonomy(context: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Inspect low stock, notification alerts (GST / debt), and return suggested intents.

    Each item is a hint for the orchestrator brain — **not** an executed action.
    """
    oid = int(context.get("organization_id") or 0)
    if oid <= 0:
        return []

    suggestions: list[dict[str, Any]] = []

    thr_raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
    try:
        thr = max(0, min(10_000, int(thr_raw)))
    except ValueError:
        thr = 5

    try:
        from services.analytics_service import list_low_stock_alerts_sync

        snap = list_low_stock_alerts_sync(oid, threshold=thr, limit=25)
        for it in snap.get("items") or []:
            sku = (it.get("sku_name") or "").strip()
            if not sku:
                continue
            cur = float(it.get("quantity") or 0)
            need = max(1.0, float(thr) - cur)
            suggestions.append(
                {
                    "intent": "add_inventory",
                    "reason": "low_stock",
                    "entity": sku,
                    "quantity": need,
                    "priority": "high",
                    "reference": {
                        "current_qty": cur,
                        "threshold": thr,
                        "location": (it.get("location") or "").strip(),
                    },
                }
            )
    except Exception:
        pass

    try:
        from workers.alert_system import list_active_alerts_for_organization

        alerts = list_active_alerts_for_organization(organization_id=oid, limit=50)
        for item in alerts.get("items") or []:
            kind = str(item.get("kind") or "")
            blob = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
            if "gst" in kind.lower() or "gst" in blob:
                suggestions.append(
                    {
                        "intent": "read_inventory",
                        "reason": "gst_pending_or_review",
                        "entity": "",
                        "quantity": None,
                        "priority": "medium",
                        "reference": {
                            "notification_id": item.get("id"),
                            "kind": kind,
                        },
                    }
                )
            elif kind == "debt_overdue":
                suggestions.append(
                    {
                        "intent": "read_inventory",
                        "reason": "system_alert_debt_overdue",
                        "entity": "",
                        "quantity": None,
                        "priority": "high",
                        "reference": {
                            "notification_id": item.get("id"),
                            "kind": kind,
                        },
                    }
                )
    except Exception:
        pass

    return suggestions
