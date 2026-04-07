"""
Operator-facing business decisions — **suggestions only** (no pricing or procurement execution).

Feeds off ``analyze_revenue`` output and tenant snapshot (inventory, dashboard).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.observability import log_structured


def _dec(s: Any) -> Decimal:
    try:
        return Decimal(str(s).replace(",", "").strip() or "0")
    except Exception:
        return Decimal("0")


def analyze_business_decisions(context: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return structured decision hints, e.g. ``increase_price``, ``reduce_cost``, ``restock_fast_items``.

    Expects ``context['_revenue_analysis']`` from ``revenue_engine.analyze_revenue`` when available.
    """
    oid = int(context.get("organization_id") or 0)
    request_id = context.get("request_id")
    state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
    rev_a = context.get("_revenue_analysis") if isinstance(context.get("_revenue_analysis"), dict) else {}

    out: list[dict[str, Any]] = []

    if rev_a.get("ok") and rev_a.get("weekly_trend") == "soft_vs_monthly_run_rate":
        out.append(
            {
                "decision": "boost_demand",
                "reason": "weekly_revenue_trailing_monthly_run_rate",
                "source": "business_decision_engine",
            }
        )

    pe = rev_a.get("profit_estimate") if isinstance(rev_a.get("profit_estimate"), dict) else {}
    if pe.get("estimated_gross_margin_inr_today") is not None:
        try:
            mg = float(pe["estimated_gross_margin_inr_today"])
        except (TypeError, ValueError):
            mg = 0.0
        if mg < 0:
            out.append(
                {
                    "decision": "increase_price",
                    "reason": "negative_gross_proxy_review_pricing_or_costs",
                    "source": "business_decision_engine",
                }
            )
            out.append(
                {
                    "decision": "reduce_cost",
                    "reason": "negative_gross_proxy_validate_supplier_and_inventory_valuation",
                    "source": "business_decision_engine",
                }
            )
        elif mg == 0 and _dec(rev_a.get("today_revenue_inr") or "0") > 0:
            out.append(
                {
                    "decision": "reduce_cost",
                    "reason": "thin_or_zero_margin_proxy_review_unit_costs",
                    "source": "business_decision_engine",
                }
            )

    for al in rev_a.get("alerts") or []:
        if isinstance(al, dict) and al.get("code") == "no_revenue_today":
            out.append(
                {
                    "decision": "marketing_push",
                    "reason": "no_sales_today_with_prior_activity",
                    "source": "business_decision_engine",
                }
            )

    low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
    top = []
    dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
    if dash.get("ok"):
        top = dash.get("top_selling_products") or []
    fast_skus = {str(x.get("sku_name") or "").lower() for x in top if isinstance(x, dict)}
    if low.get("ok") and fast_skus:
        for it in low.get("items") or []:
            if not isinstance(it, dict):
                continue
            sku = str(it.get("sku_name") or "").lower()
            if sku in fast_skus:
                out.append(
                    {
                        "decision": "restock_fast_items",
                        "reason": f"fast_mover_{sku}_is_low_stock",
                        "source": "business_decision_engine",
                        "entity": it.get("sku_name"),
                    }
                )
                break

    log_structured(
        "business_decision_engine.analyze",
        request_id=request_id,
        organization_id=oid,
        decisions=len(out),
    )
    return out[:24]
