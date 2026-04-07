"""
Map prioritized business decisions → planned steps (intents or suggestion-only rows).

Does not execute; ``multi_agent_cycle`` applies ``auto_mode`` and ``tool_executor`` guards.
"""

from __future__ import annotations

from typing import Any

from core.observability import log_structured


def _restock_quantity(state: dict[str, Any], sku: str | None) -> float | None:
    if not sku:
        return None
    low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
    thr = int(low.get("threshold") or 5)
    for it in low.get("items") or []:
        if not isinstance(it, dict):
            continue
        if (it.get("sku_name") or "").strip() != sku.strip():
            continue
        cur = float(it.get("quantity") or 0)
        return max(1.0, float(thr) - cur)
    return None


def build_action_plan(
    decisions: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Each step includes ``from_decision`` for strategy memory + tracking.

    Executable intents emitted here are only those the pipeline allows (``add_inventory``, ``read_inventory``).
    """
    ctx = context if isinstance(context, dict) else {}
    state = ctx.get("_tenant_state") if isinstance(ctx.get("_tenant_state"), dict) else {}
    oid = int(ctx.get("organization_id") or 0)

    plan: list[dict[str, Any]] = []

    for d in decisions:
        if not isinstance(d, dict):
            continue
        dec = str(d.get("decision") or "").strip()
        if not dec:
            continue

        if dec == "restock_fast_items":
            sku = d.get("entity")
            qty = _restock_quantity(state, str(sku) if sku else None)
            step: dict[str, Any] = {
                "from_decision": dec,
                "decision_ref": dict(d),
                "intent": "add_inventory" if qty is not None and oid > 0 else None,
                "type": "execute" if qty is not None and oid > 0 else "suggestion",
                "entity": str(sku or "").strip(),
                "quantity": qty,
                "priority": "high",
            }
            if qty is None:
                step["detail"] = "could_not_resolve_restock_quantity_from_snapshot"
            plan.append(step)
            continue

        if dec in ("increase_price", "reduce_cost", "marketing_push", "boost_demand"):
            plan.append(
                {
                    "from_decision": dec,
                    "decision_ref": dict(d),
                    "intent": None,
                    "type": "suggestion",
                    "priority": "high" if dec in ("increase_price", "reduce_cost") else "medium",
                    "detail": d.get("reason") or "operator_review_required",
                }
            )
            continue

        plan.append(
            {
                "from_decision": dec,
                "decision_ref": dict(d),
                "intent": None,
                "type": "suggestion",
                "priority": "low",
                "detail": "unmapped_decision_manual_review",
            }
        )

    log_structured(
        "action_planner.complete",
        request_id=request_id,
        organization_id=oid,
        steps=len(plan),
    )
    return plan[:32]
