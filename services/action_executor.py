"""
Phase 3 — execute validated AI decisions using existing Phase 2 services (allowlist only).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from core.decision_schema import AIDecision
from services import audit_log as system_audit
from services import billing_phase2_service as bill2
from services import inventory_phase2_service as inv2
from services import inventory_service as inv_legacy
from services import production_phase2_service as prod2


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

    if act == "reorder_stock":
        lines = decision.data.get("lines")
        if decision.data.get("supplier_id") and isinstance(lines, list) and len(lines) > 0:
            sid = int(decision.data.get("supplier_id") or 0)
            od = decision.data.get("order_date")
            if isinstance(od, str) and od.strip():
                parts = od.strip().split("-")
                order_date = date(int(parts[0]), int(parts[1]), int(parts[2])) if len(parts) == 3 else date.today()
            else:
                order_date = date.today()
            out = inv2.create_purchase_order_sync(
                organization_id=oid,
                supplier_id=sid,
                order_date=order_date,
                expected_date=None,
                notes=decision.data.get("notes"),
                lines=lines,
                user_id=uid,
            )
            if not out.get("ok"):
                return {"ok": False, "error": out.get("error") or "PO create failed"}
            return {"ok": True, "result": out}

        sku = str(decision.data.get("sku_name") or "").strip()
        qty = float(decision.data.get("quantity") or 0)
        loc = str(decision.data.get("location") or "").strip()
        out = inv_legacy.add_inventory_sync(
            organization_id=oid,
            sku_name=sku,
            quantity=qty,
            location=loc,
            user_id=uid,
        )
        if not out.get("ok"):
            return {"ok": False, "error": out.get("error") or "add_inventory failed"}
        system_audit.record_system_audit(
            action=system_audit.ACTION_STOCK_UPDATE,
            outcome="success",
            organization_id=oid,
            user_id=uid,
            resource_type="ai_decision",
            metadata={"channel": "action_executor.reorder_stock", "decision_action": act},
        )
        return {"ok": True, "result": out}

    if act == "record_stock_movement":
        iid = int(decision.data.get("inventory_item_id") or 0)
        delta = float(decision.data.get("quantity_delta") or 0)
        out = inv2.record_stock_movement_sync(
            organization_id=oid,
            inventory_item_id=iid,
            quantity_delta=delta,
            movement_type=str(decision.data.get("movement_type") or "ADJUST")[:32],
            reference_type="ai_decision",
            reference_id=str(decision.data.get("reference_id") or ""),
            user_id=uid,
        )
        if not out.get("ok"):
            return {"ok": False, "error": out.get("error") or "movement failed"}
        return {"ok": True, "result": out}

    if act == "mark_invoice_paid":
        iid = int(decision.data.get("invoice_id") or 0)
        amt = float(decision.data.get("amount_inr") or 0)
        out = bill2.record_payment_sync(
            organization_id=oid,
            invoice_id=iid,
            amount_inr=amt,
            method=str(decision.data.get("method") or "bank")[:32],
            reference=decision.data.get("reference"),
            user_id=uid,
        )
        if not out.get("ok"):
            return {"ok": False, "error": out.get("error") or "payment failed"}
        return {"ok": True, "result": out}

    if act == "create_purchase_order":
        sid = int(decision.data.get("supplier_id") or 0)
        lines = decision.data.get("lines") or []
        od = decision.data.get("order_date")
        if isinstance(od, str) and od.strip():
            parts = od.strip().split("-")
            order_date = date(int(parts[0]), int(parts[1]), int(parts[2])) if len(parts) == 3 else date.today()
        else:
            order_date = date.today()
        out = inv2.create_purchase_order_sync(
            organization_id=oid,
            supplier_id=sid,
            order_date=order_date,
            expected_date=None,
            notes=decision.data.get("notes"),
            lines=lines if isinstance(lines, list) else [],
            user_id=uid,
        )
        if not out.get("ok"):
            return {"ok": False, "error": out.get("error") or "PO create failed"}
        return {"ok": True, "result": out}

    if act in ("send_alert", "send_payment_reminder"):
        msg = str(decision.data.get("message") or "").strip()[:2000]
        iid = int(decision.data.get("invoice_id") or 0) if act == "send_payment_reminder" else None
        meta: dict[str, Any] = {
            "channel": f"action_executor.{act}",
            "message": msg,
            "dashboard": True,
        }
        if act == "send_payment_reminder":
            meta["reminder_type"] = "payment_reminder"
            if iid:
                meta["invoice_id"] = iid
        system_audit.record_system_audit(
            action="ai_alert",
            outcome="success",
            organization_id=oid,
            user_id=uid,
            resource_type="notification",
            metadata=meta,
        )
        return {
            "ok": True,
            "result": {
                "alert_recorded": True,
                "message": msg,
                "dashboard": True,
                "kind": "payment_reminder" if act == "send_payment_reminder" else "general",
            },
        }

    if act == "create_task":
        aid = int(decision.data.get("asset_id") or 0)
        out = prod2.create_production_log_sync(
            organization_id=oid,
            asset_id=aid,
            production_unit=str(decision.data.get("production_unit") or "general")[:64],
            cement_in=decision.data.get("cement_in"),
            sand_in=decision.data.get("sand_in"),
            blocks_out=decision.data.get("blocks_out"),
            raw_material_in=decision.data.get("raw_material_in"),
            yield_out=decision.data.get("yield_out"),
            labor_cost=decision.data.get("labor_cost"),
            external_ref=decision.data.get("external_ref"),
            raw_consumptions=decision.data.get("raw_consumptions")
            if isinstance(decision.data.get("raw_consumptions"), list)
            else None,
            user_id=uid,
        )
        if not out.get("ok"):
            return {"ok": False, "error": out.get("error") or "create_production_log failed"}
        return {"ok": True, "result": out}

    return {"ok": False, "error": f"unhandled action: {act}"}
