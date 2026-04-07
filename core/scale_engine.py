"""
Scale / packaging hints: which capabilities could become **standalone SaaS products**.

**Suggestions only** — no provisioning, billing of third parties, or infra changes.
"""

from __future__ import annotations

from typing import Any

from core.observability import log_structured


def detect_scale_products(context: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return ``product`` rows describing monetizable modules (for operator planning).

    Complements ``saas_factory.run_saas_factory`` with a **scale / GTM** lens.
    """
    oid = int(context.get("organization_id") or 0)
    request_id = context.get("request_id")
    state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}

    products: list[dict[str, Any]] = []

    if int(state.get("inventory_row_count") or 0) > 0:
        products.append(
            {
                "product": "Inventory SaaS",
                "reason": "multi_sku_operations_ready_for_tenant_isolation_and_api",
                "source": "scale_engine",
            }
        )

    dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
    if dash.get("ok"):
        rev = dash.get("revenue_inr") or {}
        if _money_positive(rev.get("this_month")):
            products.append(
                {
                    "product": "Billing SaaS",
                    "reason": "documented_bill_volume_suggests_reusable_pos_billing_layer",
                    "source": "scale_engine",
                }
            )

    notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
    if (notes.get("unread_count") or len(notes.get("items") or [])) > 0:
        products.append(
            {
                "product": "Alerts & Control Tower SaaS",
                "reason": "notification_volume_indicates_cross_tenant_event_stream_value",
                "source": "scale_engine",
            }
        )

    low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
    if low.get("ok") and int(low.get("count") or 0) > 0:
        products.append(
            {
                "product": "Low-stock automation SaaS",
                "reason": "repeatable_replenishment_workflows_across_skus",
                "source": "scale_engine",
            }
        )

    products.append(
        {
            "product": "Multi-agent ops cockpit SaaS",
            "reason": "compose_managers_and_workers_as_white_label_operator_console",
            "source": "scale_engine",
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

    log_structured(
        "scale_engine.detect",
        request_id=request_id,
        organization_id=oid,
        products=len(uniq),
    )
    return uniq[:16]


def _money_positive(v: Any) -> bool:
    try:
        return float(str(v).replace(",", "").strip() or "0") > 0
    except ValueError:
        return False
