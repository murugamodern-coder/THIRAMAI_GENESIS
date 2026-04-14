"""
Inventory service facade: **add** / **deduct** stock with org scope and audit.

Delegates mutations to ``services.inventory_ops.apply_inventory_delta`` (same path as sell flows).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.database import get_session_factory
from services import audit_log as system_audit
from services.inventory_ops import apply_inventory_delta


def add_inventory_sync(
    *,
    organization_id: int,
    sku_name: str,
    quantity: float | Decimal,
    location: str = "",
    unit_price: float | Decimal | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Increase stock for a SKU (creates row if missing)."""
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    sku = (sku_name or "").strip()
    if not sku:
        return {"ok": False, "error": "sku_name required"}
    qty = Decimal(str(quantity))
    if qty <= 0:
        return {"ok": False, "error": "quantity must be positive"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    loc = (location or "").strip()
    with factory() as session:
        with session.begin():
            row = apply_inventory_delta(session, organization_id=oid, sku_name=sku, location=loc, delta=qty)
            if unit_price is not None:
                up = Decimal(str(unit_price))
                if up >= 0:
                    row.unit_price = up
                    if row.quantity is not None:
                        row.total_value = (row.quantity * up).quantize(Decimal("0.01"))
            iid = int(row.id)

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="inventory",
        metadata={
            "channel": "inventory_service.add",
            "sku": sku[:128],
            "quantity_delta": float(qty),
            "location": loc[:128],
            "inventory_id": iid,
        },
    )
    return {"ok": True, "inventory_id": iid, "sku_name": sku, "organization_id": oid}


def deduct_inventory_sync(
    *,
    organization_id: int,
    sku_name: str,
    quantity: float | Decimal,
    location: str = "",
    user_id: int | None = None,
) -> dict[str, Any]:
    """Decrease stock (raises internally as ValueError → surfaced as error string)."""
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    sku = (sku_name or "").strip()
    if not sku:
        return {"ok": False, "error": "sku_name required"}
    qty = Decimal(str(quantity))
    if qty <= 0:
        return {"ok": False, "error": "quantity must be positive"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    loc = (location or "").strip()
    try:
        with factory() as session:
            with session.begin():
                row = apply_inventory_delta(session, organization_id=oid, sku_name=sku, location=loc, delta=-qty)
                iid = int(row.id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="inventory",
        metadata={
            "channel": "inventory_service.deduct",
            "sku": sku[:128],
            "quantity_delta": float(-qty),
            "location": loc[:128],
            "inventory_id": iid,
        },
    )
    return {"ok": True, "inventory_id": iid, "sku_name": sku, "organization_id": oid}


from services.inventory_phase2_service import (  # noqa: E402
    create_inventory_item_sync,
    create_purchase_order_sync,
    create_supplier_sync,
    list_inventory_items_sync,
    list_low_stock_alerts_sync,
    list_purchase_orders_sync,
    list_stock_movements_sync,
    list_supplier_payments_sync,
    list_suppliers_sync,
    receive_purchase_order_line_sync,
    record_stock_movement_sync,
    record_supplier_payment_sync,
    update_inventory_item_sync,
    update_purchase_order_supplier_invoice_sync,
)
