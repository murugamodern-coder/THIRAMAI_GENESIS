"""P4.5 single execution authority adapter for AI decisions."""

from __future__ import annotations

import logging
from typing import Any

from core.decision_schema import AIDecision

_LOG = logging.getLogger(__name__)


def _decision_to_command(decision: AIDecision) -> str:
    act = str(decision.action or "").strip().lower()
    d = decision.data if isinstance(decision.data, dict) else {}
    if act == "reorder_stock":
        sku = str(d.get("sku_name") or "").strip()
        qty = d.get("quantity")
        loc = str(d.get("location") or "").strip()
        return f"Reorder stock sku={sku} quantity={qty} location={loc}".strip()
    if act == "record_stock_movement":
        return (
            f"Record stock movement inventory_item_id={d.get('inventory_item_id')} "
            f"quantity_delta={d.get('quantity_delta')} movement_type={d.get('movement_type')}"
        ).strip()
    if act == "mark_invoice_paid":
        return (
            f"Mark invoice paid invoice_id={d.get('invoice_id')} amount_inr={d.get('amount_inr')} "
            f"method={d.get('method')}"
        ).strip()
    if act == "create_purchase_order":
        return f"Create purchase order supplier_id={d.get('supplier_id')}".strip()
    if act in {"send_alert", "send_payment_reminder"}:
        return f"Send alert message={str(d.get('message') or '')[:180]}".strip()
    if act == "create_task":
        return f"Create production task asset_id={d.get('asset_id')}".strip()
    return f"Execute approved ai decision action={act}".strip()


def execute_decision(
    *,
    organization_id: int,
    decision: AIDecision,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Run one decision. Returns ``{ok, result}`` or ``{ok: False, error}``.
    """
    oid = int(organization_id)
    uid = user_id if user_id and int(user_id) > 0 else None
    act = decision.action

    if act == "noop":
        return {"ok": True, "result": {"message": "noop"}}

    # P4.5 lock: route all executable decisions through the single brain authority.
    if uid is None:
        return {"ok": False, "error": "single_execution_authority_requires_user_id"}
    try:
        from services.brain_execute import brain_execute

        routed = brain_execute(
            _decision_to_command(decision),
            int(uid),
            int(oid),
        )
    except Exception as exc:
        _LOG.exception("action_executor brain routing failed for action=%s", act)
        return {"ok": False, "error": f"brain_execute_route_failed:{type(exc).__name__}"}
    return {
        "ok": bool((routed.get("result") or {}).get("ok")),
        "result": {
            "routed_via": "brain_execute",
            "brain_status": routed.get("status"),
            "brain_result": routed.get("result"),
            "run_closure": routed.get("closure"),
        },
    }
