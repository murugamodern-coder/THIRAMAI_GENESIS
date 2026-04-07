"""
Growth ideas (products, bundles, adjacent SKUs) — **suggestions only**; no auto-selling.
"""

from __future__ import annotations

from typing import Any

from core.observability import log_structured


def detect_growth_ideas(context: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return ``idea`` rows derived from inventory labels, top sellers, and compliance gaps.

    Context should include ``_tenant_state`` when run inside the multi-agent pipeline.
    """
    oid = int(context.get("organization_id") or 0)
    request_id = context.get("request_id")
    state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}

    ideas: list[dict[str, Any]] = []

    top: list[dict[str, Any]] = []
    dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
    if dash.get("ok"):
        top = [x for x in (dash.get("top_selling_products") or []) if isinstance(x, dict)]

    inv_blob = ""
    low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
    for it in (low.get("items") or [])[:15]:
        if isinstance(it, dict):
            inv_blob += f" {it.get('sku_name') or ''}"

    blob_l = inv_blob.lower()
    if any(k in blob_l for k in ("solar", "panel", "pv", "inverter")):
        ideas.append(
            {
                "idea": "Bundle solar kits with installation checklist",
                "reason": "inventory_signals_solar_related_skus",
                "source": "growth_engine",
            }
        )

    if top:
        ideas.append(
            {
                "idea": f"Create starter packs around top seller: {top[0].get('sku_name')}",
                "reason": "double_down_on_proven_velocity",
                "source": "growth_engine",
            }
        )

    notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
    for item in notes.get("items") or []:
        if not isinstance(item, dict):
            continue
        t = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
        if "gst" in t:
            ideas.append(
                {
                    "idea": "Create GST SaaS / compliance add-on for your customers",
                    "reason": "active_gst_notifications_in_tenant",
                    "source": "growth_engine",
                }
            )
            break

    if int(state.get("inventory_row_count") or 0) > 5 and not ideas:
        ideas.append(
            {
                "idea": "Launch a subscription replenishment offer for repeat B2B buyers",
                "reason": "broad_catalog_suitable_for_recurring_revenue",
                "source": "growth_engine",
            }
        )

    log_structured(
        "growth_engine.detect",
        request_id=request_id,
        organization_id=oid,
        ideas=len(ideas),
    )
    return ideas[:20]
