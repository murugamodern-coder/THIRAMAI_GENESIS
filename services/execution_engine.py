"""
Stage-5 execution bridge: map validated ``action_intent`` JSON to side effects **only after HITL**.

No inventory mutation, invoice PDFs, or stock receipts run until an **Owner** or **Manager**
approves via ``POST /actions/approvals/{id}/resolve`` (same guard as other high-risk actions).

Flow:
1. ``queue_action_intent_for_hitl`` — validate intent → ``approvals`` row (``action_type=brain_action_intent``).
2. Approver confirms with ``{"confirm":"YES"}`` → background job calls ``execute_approved_intent_payload``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

import asset_portal
from core.brain_output import (
    ActionIntent,
    ActionIntentNone,
    CreateInvoiceAction,
    OrderStockAction,
    SellStockAction,
    TriggerSolarResearchAction,
    UpdateStockAction,
    parse_action_intent_dict,
)
from core.database import get_session_factory
from factory.billing_tool import build_invoice_pdf, default_invoice_path
from services import approval_store
from services import audit_log as system_audit
from services import sale_execution
from services.inventory_ops import apply_inventory_delta

# Stored on ``approvals.action_type``; branch in ``api.routes.billing.resolve_approval_action``.
BRAIN_ACTION_INTENT_TYPE = "brain_action_intent"

# Approver RBAC is enforced on the HTTP route (``require_roles("owner", "manager")``).
REQUIRED_APPROVER_ROLES = ("owner", "manager")


def _summary_for_intent(intent: ActionIntent) -> str:
    if isinstance(intent, CreateInvoiceAction):
        return (
            f"Brain intent: create_invoice buyer={intent.buyer} grade={intent.grade} "
            f"weight={intent.weight} rate={intent.rate}"
        )
    if isinstance(intent, OrderStockAction):
        return f"Brain intent: order_stock sku={intent.sku_name} qty={intent.quantity}"
    if isinstance(intent, UpdateStockAction):
        return f"Brain intent: update_stock sku={intent.sku_name} delta={intent.quantity_delta}"
    if isinstance(intent, SellStockAction):
        return f"Brain intent: sell_stock sku={intent.sku_name} qty={intent.quantity}"
    if isinstance(intent, TriggerSolarResearchAction):
        return "Brain intent: trigger_solar_research (inline — no HITL queue)"
    return "Brain intent: none"


def queue_action_intent_for_hitl(
    *,
    organization_id: int,
    action_intent: dict[str, Any],
    created_by_user_id: int | None,
) -> dict[str, Any]:
    """
    Validate ``action_intent`` and create a **pending** approval row.

    Does **not** execute mutations. Returns ``pending_approval`` + ``approval_id``, or ``no_action`` / ``invalid``.
    """
    if not isinstance(action_intent, dict):
        return {"status": "invalid", "message": "action_intent must be a JSON object"}
    try:
        intent = parse_action_intent_dict(action_intent)
    except Exception as exc:
        return {
            "status": "invalid",
            "message": f"action_intent validation failed: {type(exc).__name__}: {exc}",
        }
    if isinstance(intent, TriggerSolarResearchAction):
        return {
            "status": "no_action",
            "message": "trigger_solar_research is fulfilled in the brain/orchestrator response — not queued for HITL.",
        }
    if isinstance(intent, ActionIntentNone) or intent.kind == "none":
        return {
            "status": "no_action",
            "message": "action_intent.kind is none - nothing to queue for approval.",
        }
    summary = _summary_for_intent(intent)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "intent_kind": intent.kind,
        "intent": intent.model_dump(mode="json"),
    }
    aid = approval_store.create_pending(
        organization_id=int(organization_id),
        action_type=BRAIN_ACTION_INTENT_TYPE,
        risk_tier=approval_store.RiskTier.high,
        payload=payload,
        summary=summary,
        created_by=created_by_user_id,
    )
    return {
        "status": "pending_approval",
        "approval_id": aid,
        "intent_kind": intent.kind,
        "summary": summary,
        "message": 'POST /actions/approvals/{id}/resolve with {"confirm":"YES"} as Owner/Manager to execute.',
    }


def _execute_update_stock(intent: UpdateStockAction, organization_id: int) -> dict[str, Any]:
    delta = Decimal(str(intent.quantity_delta))
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not set")
    with factory() as session:
        with session.begin():
            row = apply_inventory_delta(
                session,
                organization_id=int(organization_id),
                sku_name=intent.sku_name.strip(),
                location=intent.location or "",
                delta=delta,
            )
    nq = float(row.quantity)
    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=int(organization_id),
        resource_type="inventory",
        metadata={
            "sku": (intent.sku_name or "")[:128],
            "delta": str(intent.quantity_delta),
            "new_quantity": nq,
            "channel": "execution_engine",
        },
    )
    return {
        "ok": True,
        "executed": "update_stock",
        "sku_name": intent.sku_name,
        "new_quantity": nq,
        "location": intent.location or "",
    }


def _execute_order_stock(intent: OrderStockAction, organization_id: int) -> dict[str, Any]:
    """Treat approved order as stock receipt (positive add)."""
    delta = float(intent.quantity)
    sub = UpdateStockAction(
        sku_name=intent.sku_name,
        quantity_delta=delta,
        location=intent.location,
    )
    out = _execute_update_stock(sub, organization_id)
    out["executed"] = "order_stock"
    if intent.notes:
        out["notes"] = intent.notes
    return out


def _execute_create_invoice(intent: CreateInvoiceAction, organization_id: int) -> dict[str, Any]:
    from services import billing_guard

    billing_guard.assert_billing_not_paused(int(organization_id))
    inv_date = (intent.invoice_date or "").strip() or date.today().isoformat()
    inv_no = (intent.invoice_no or "").strip() or f"INV-{inv_date.replace('-', '')}-BRAIN"
    out = default_invoice_path()
    path = build_invoice_pdf(
        buyer_name=intent.buyer,
        buyer_address=intent.buyer_address or "-",
        invoice_no=inv_no,
        invoice_date=inv_date,
        length_m=float(intent.length),
        grade=intent.grade,
        weight_kg=float(intent.weight),
        rate_per_kg=float(intent.rate),
        gst_percent=float(intent.gst),
        seller_name=intent.seller,
        seller_address=intent.seller_address or "-",
        seller_gstin=intent.seller_gstin or "-",
        out_path=out,
        organization_id=int(organization_id),
        append_master_index=True,
    )
    rel = path.relative_to(asset_portal.FACTORY_OUTPUT.resolve()).as_posix()
    subtotal = float(intent.weight) * float(intent.rate)
    gst_amt = subtotal * (float(intent.gst) / 100.0)
    grand = subtotal + gst_amt
    asset_portal.append_sales_history_entry(
        {
            "invoice_no": inv_no,
            "invoice_date": inv_date,
            "relative_path": rel,
            "buyer": intent.buyer,
            "buyer_address": intent.buyer_address,
            "length_m": intent.length,
            "grade": intent.grade,
            "weight_kg": intent.weight,
            "rate_per_kg_inr": intent.rate,
            "gst_percent": intent.gst,
            "subtotal_inr": round(subtotal, 2),
            "gst_inr": round(gst_amt, 2),
            "grand_total_inr": round(grand, 2),
            "seller": intent.seller,
            "seller_gstin": intent.seller_gstin,
            "source": "execution_engine_brain_intent",
            "organization_id": int(organization_id),
        }
    )
    asset_portal.sync_index_cursor_to_end()
    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=int(organization_id),
        resource_type="invoice",
        metadata={
            "invoice_no": inv_no[:64],
            "grand_total_inr": round(grand, 2),
            "source": "execution_engine_brain_intent",
        },
    )
    return {
        "ok": True,
        "executed": "create_invoice",
        "relative_path": rel,
        "url": asset_portal.factory_url_for_relative(rel),
        "invoice_no": inv_no,
    }


def execute_approved_intent_payload(
    payload: dict[str, Any],
    *,
    organization_id: int,
    resolved_by_user_id: int | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the approved intent (called from background worker after HITL).

    ``payload`` is the approval row's JSONB (must contain ``intent`` object).
    """
    raw = payload.get("intent")
    if not isinstance(raw, dict):
        raise ValueError("approval payload missing intent object")
    intent = parse_action_intent_dict(raw)
    if isinstance(intent, ActionIntentNone) or intent.kind == "none":
        return {"ok": True, "skipped": True, "message": "intent kind is none"}
    if isinstance(intent, TriggerSolarResearchAction):
        return {
            "ok": True,
            "skipped": True,
            "message": "trigger_solar_research is not executed via HITL (already inline in brain).",
        }
    oid = int(organization_id)
    if isinstance(intent, CreateInvoiceAction):
        return _execute_create_invoice(intent, oid)
    if isinstance(intent, OrderStockAction):
        return _execute_order_stock(intent, oid)
    if isinstance(intent, UpdateStockAction):
        return _execute_update_stock(intent, oid)
    if isinstance(intent, SellStockAction):
        return _execute_sell_stock(
            intent,
            oid,
            resolved_by_user_id=resolved_by_user_id,
            correlation_id=correlation_id,
        )
    raise ValueError(f"unsupported intent kind: {getattr(intent, 'kind', intent)}")


def _execute_sell_stock(
    intent: SellStockAction,
    organization_id: int,
    *,
    resolved_by_user_id: int | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    approver = (
        int(resolved_by_user_id)
        if resolved_by_user_id is not None and int(resolved_by_user_id) > 0
        else None
    )
    # Post–HITL execution: evaluate policy as owner-tier (sovereign approval already obtained).
    out = sale_execution.execute_sell_stock_sync(
        organization_id=int(organization_id),
        sku_name=intent.sku_name.strip(),
        quantity=float(intent.quantity),
        location=intent.location or "",
        principal_user_id=approver,
        principal_role_level=1,
        correlation_id=correlation_id,
    )
    try:
        from services.ltm_hooks import record_inventory_sell_execution

        record_inventory_sell_execution(
            organization_id=int(organization_id),
            prompt_context="execution_engine HITL-approved sell_stock",
            sku_name=intent.sku_name.strip(),
            quantity=float(intent.quantity),
            location=intent.location or "",
            result=out,
            correlation_id=correlation_id,
        )
    except Exception:
        pass
    if not out.get("ok"):
        raise ValueError(out.get("error") or "sell_stock failed")
    return {
        "ok": True,
        "executed": "sell_stock",
        "bill_id": out["bill_id"],
        "total_amount": out["total_amount"],
        "sku_name": out["sku_name"],
        "quantity_sold": out["quantity_sold"],
        "remaining_quantity": out["remaining_quantity"],
        "items": out["items"],
    }
