"""
SaaS factory automation hints — **suggestions only** (no code generation, no provisioning).

Uses the same tenant snapshot as multi-agent cycles (``_tenant_state``).
"""

from __future__ import annotations

from typing import Any


def run_saas_factory(context: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return a list of product ideas the operator might adopt (marketing copy level only).

    Context should include ``_tenant_state`` (from ``observe_tenant_state``). If missing, returns [].
    """
    state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
    oid = int(state.get("organization_id") or context.get("organization_id") or 0)
    if oid <= 0:
        return []

    products: list[dict[str, Any]] = []

    low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
    missing_gst_meta = False
    for it in low.get("items") or []:
        if not isinstance(it, dict):
            continue
        if it.get("gst_rate_percent") is None and (it.get("hsn_code") in (None, "")):
            missing_gst_meta = True
            break

    notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
    gst_alert = False
    for item in notes.get("items") or []:
        if not isinstance(item, dict):
            continue
        blob = f"{item.get('kind') or ''} {item.get('title') or ''} {item.get('body') or ''}".lower()
        if "gst" in blob:
            gst_alert = True
            break

    if missing_gst_meta or gst_alert:
        products.append(
            {
                "product": "GST Automation SaaS",
                "reason": "inventory_or_alerts_suggest_gst_metadata_and_filing_workflow",
            }
        )

    dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
    if dash.get("ok"):
        top = dash.get("top_selling_products") or []
        rev = dash.get("revenue_inr") or {}
        if len(top) > 0 or _money_positive(rev.get("this_month")):
            products.append(
                {
                    "product": "Billing & POS SaaS",
                    "reason": "active_sales_history_suggests_billing_and_receipt_automation",
                }
            )

    if int(state.get("inventory_row_count") or 0) > 0 or (low.get("ok") and int(low.get("count") or 0) > 0):
        products.append(
            {
                "product": "Inventory & Low-Stock SaaS",
                "reason": "tenant_has_inventory_rows_needs_ops_dashboard_and_alerts",
            }
        )

    products.append(
        {
            "product": "Executive Dashboard SaaS",
            "reason": "cross_domain_visibility_for_ceo_and_managers",
        }
    )

    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for p in products:
        key = str(p.get("product") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def _money_positive(v: Any) -> bool:
    try:
        return float(str(v).replace(",", "").strip() or "0") > 0
    except ValueError:
        return False
