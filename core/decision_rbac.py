"""RBAC checks for executing AI decisions (Phase 3)."""

from __future__ import annotations

from core.decision_schema import AIDecision
from core.permission_engine import role_has_permission
from core.rbac import Permission


def can_execute_decision(*, role_name: str, decision: AIDecision) -> tuple[bool, str | None]:
    """
    Return (True, None) if the role may execute this action, else (False, reason).
    """
    rn = (role_name or "customer").lower()
    act = decision.action

    if act in ("noop", "send_alert", "send_payment_reminder"):
        return True, None

    if act in ("mark_invoice_paid", "create_purchase_order"):
        if not role_has_permission(role_name=rn, permission_name=Permission.BILLING_MANAGE.value):
            return False, "missing permission billing.manage for this action"
        return True, None

    if act == "reorder_stock":
        lines = decision.data.get("lines")
        if decision.data.get("supplier_id") and isinstance(lines, list) and len(lines) > 0:
            if not role_has_permission(role_name=rn, permission_name=Permission.BILLING_MANAGE.value):
                return False, "missing permission billing.manage for purchase-order reorder"
            return True, None
        if not role_has_permission(role_name=rn, permission_name=Permission.INVENTORY_WRITE.value):
            return False, "missing permission inventory.write for this action"
        return True, None

    if act == "record_stock_movement":
        if not role_has_permission(role_name=rn, permission_name=Permission.INVENTORY_WRITE.value):
            return False, "missing permission inventory.write for this action"
        return True, None

    if act == "create_task":
        if not role_has_permission(role_name=rn, permission_name=Permission.PRODUCTION_WRITE.value):
            return False, "missing permission production.write for this action"
        return True, None

    return False, f"action {act} is not executable for role-gated checks"
