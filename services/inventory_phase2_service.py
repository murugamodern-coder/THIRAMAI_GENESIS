"""
Phase 2 enterprise inventory: ``inventory_items``, ``stock_movements``, suppliers, purchase orders.

Quantity changes mirror into legacy ``inventory`` (``apply_inventory_delta``) so retail sell flows stay consistent.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import (
    InventoryItem,
    OrganizationLiquidity,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMovement,
    Supplier,
    SupplierPayment,
)
from services import audit_log as system_audit
from services.inventory_ops import apply_inventory_delta


def _dec(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def _serialize_item(row: InventoryItem) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "organization_id": int(row.organization_id),
        "sku_name": row.sku_name,
        "quantity": float(row.quantity or 0),
        "location": row.location or "",
        "unit_price": float(row.unit_price) if row.unit_price is not None else None,
        "unit_cost_pre_tax": float(row.unit_cost_pre_tax) if row.unit_cost_pre_tax is not None else None,
        "total_value": float(row.total_value) if row.total_value is not None else None,
        "gst_rate_percent": float(row.gst_rate_percent) if row.gst_rate_percent is not None else None,
        "hsn_code": row.hsn_code,
        "external_ref": row.external_ref,
        "unit": row.unit or "",
        "reorder_point": float(row.reorder_point) if row.reorder_point is not None else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_movement(row: StockMovement) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "organization_id": int(row.organization_id),
        "inventory_item_id": int(row.inventory_item_id),
        "quantity_delta": float(row.quantity_delta),
        "movement_type": row.movement_type,
        "reference_type": row.reference_type,
        "reference_id": row.reference_id,
        "notes": row.notes,
        "lot_batch": getattr(row, "lot_batch", None),
        "reason": getattr(row, "reason", None),
        "created_by_user_id": int(row.created_by_user_id) if row.created_by_user_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_supplier(row: Supplier) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "organization_id": int(row.organization_id),
        "name": row.name,
        "gstin": row.gstin,
        "contact_email": row.contact_email,
        "phone": row.phone,
        "address": row.address,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _mirror_legacy_delta(
    session: Session,
    *,
    organization_id: int,
    sku_name: str,
    location: str,
    delta: Decimal,
) -> None:
    if delta == 0:
        return
    apply_inventory_delta(
        session,
        organization_id=organization_id,
        sku_name=sku_name,
        location=location,
        delta=delta,
    )


def _recalc_value(item: InventoryItem) -> None:
    if item.unit_price is not None and item.quantity is not None:
        item.total_value = (item.quantity * item.unit_price).quantize(Decimal("0.01"))


def list_inventory_items_sync(*, organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        rows = list(
            session.scalars(
                select(InventoryItem)
                .where(InventoryItem.organization_id == oid)
                .order_by(InventoryItem.sku_name, InventoryItem.location)
            ).all()
        )
    return {"ok": True, "items": [_serialize_item(r) for r in rows]}


def create_inventory_item_sync(
    *,
    organization_id: int,
    sku_name: str,
    location: str = "",
    quantity: float | Decimal = 0,
    unit_price: float | Decimal | None = None,
    unit_cost_pre_tax: float | Decimal | None = None,
    gst_rate_percent: float | Decimal | None = None,
    hsn_code: str | None = None,
    external_ref: str | None = None,
    reorder_point: float | Decimal | None = None,
    unit: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    sku = (sku_name or "").strip()
    if not sku:
        return {"ok": False, "error": "sku_name required"}
    loc = (location or "").strip()
    u = (unit or "").strip()[:32]
    qty = _dec(quantity)
    if qty < 0:
        return {"ok": False, "error": "quantity cannot be negative"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    out_item: dict[str, Any] | None = None
    iid = 0
    try:
        with factory() as session:
            with session.begin():
                row = InventoryItem(
                    organization_id=oid,
                    sku_name=sku,
                    location=loc,
                    unit=u,
                    quantity=qty,
                    unit_price=_dec(unit_price) if unit_price is not None else None,
                    unit_cost_pre_tax=_dec(unit_cost_pre_tax) if unit_cost_pre_tax is not None else None,
                    gst_rate_percent=_dec(gst_rate_percent) if gst_rate_percent is not None else None,
                    hsn_code=(hsn_code or "").strip() or None,
                    external_ref=(external_ref or "").strip() or None,
                    reorder_point=_dec(reorder_point) if reorder_point is not None else None,
                )
                _recalc_value(row)
                session.add(row)
                session.flush()
                iid = int(row.id)
                if qty != 0:
                    mov = StockMovement(
                        organization_id=oid,
                        inventory_item_id=iid,
                        quantity_delta=qty,
                        movement_type="IN" if qty > 0 else "OUT",
                        reference_type="CREATE",
                        reference_id=str(iid),
                        notes="initial stock on create",
                        created_by_user_id=user_id if user_id and user_id > 0 else None,
                    )
                    session.add(mov)
                    _mirror_legacy_delta(session, organization_id=oid, sku_name=sku, location=loc, delta=qty)
                out_item = _serialize_item(row)
    except IntegrityError:
        return {"ok": False, "error": "duplicate sku_name+location for this organization"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="inventory_item",
        metadata={
            "channel": "inventory_phase2.create",
            "inventory_item_id": iid,
            "sku": sku[:128],
            "location": loc[:128],
            "quantity": float(qty),
        },
    )
    return {"ok": True, "item": out_item}


def update_inventory_item_sync(
    *,
    organization_id: int,
    item_id: int,
    sku_name: str | None = None,
    location: str | None = None,
    quantity: float | Decimal | None = None,
    unit_price: float | Decimal | None = None,
    unit_cost_pre_tax: float | Decimal | None = None,
    gst_rate_percent: float | Decimal | None = None,
    hsn_code: str | None = None,
    external_ref: str | None = None,
    reorder_point: float | Decimal | None = None,
    unit: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    iid = int(item_id)
    if oid <= 0 or iid <= 0:
        return {"ok": False, "error": "organization_id and item_id required"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    out_item: dict[str, Any] | None = None
    with factory() as session:
        try:
            with session.begin():
                row = session.get(InventoryItem, iid)
                if row is None or int(row.organization_id) != oid:
                    raise LookupError("inventory item not found")
                old_qty = _dec(row.quantity)

                if sku_name is not None:
                    row.sku_name = (sku_name or "").strip()
                if location is not None:
                    row.location = (location or "").strip()
                if unit_price is not None:
                    row.unit_price = _dec(unit_price)
                if unit_cost_pre_tax is not None:
                    row.unit_cost_pre_tax = _dec(unit_cost_pre_tax)
                if gst_rate_percent is not None:
                    row.gst_rate_percent = _dec(gst_rate_percent)
                if hsn_code is not None:
                    row.hsn_code = (hsn_code or "").strip() or None
                if external_ref is not None:
                    row.external_ref = (external_ref or "").strip() or None
                if reorder_point is not None:
                    row.reorder_point = _dec(reorder_point)
                if unit is not None:
                    row.unit = (unit or "").strip()[:32]

                if quantity is not None:
                    new_qty = _dec(quantity)
                    if new_qty < 0:
                        raise ValueError("quantity cannot be negative")
                    delta = new_qty - old_qty
                    row.quantity = new_qty
                    if delta != 0:
                        mov = StockMovement(
                            organization_id=oid,
                            inventory_item_id=iid,
                            quantity_delta=delta,
                            movement_type="ADJUST",
                            reference_type="PUT",
                            reference_id=str(iid),
                            notes="quantity set via update",
                            created_by_user_id=user_id if user_id and user_id > 0 else None,
                        )
                        session.add(mov)
                        _mirror_legacy_delta(
                            session,
                            organization_id=oid,
                            sku_name=row.sku_name,
                            location=row.location or "",
                            delta=delta,
                        )

                _recalc_value(row)
                out_item = _serialize_item(row)
        except LookupError:
            return {"ok": False, "error": "inventory item not found"}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="inventory_item",
        metadata={"channel": "inventory_phase2.update", "inventory_item_id": iid},
    )
    if out_item is not None and quantity is not None:
        try:
            from services.jarvis_agent_event_engine import record_inventory_quantity_event_sync

            record_inventory_quantity_event_sync(
                organization_id=oid,
                inventory_item_id=iid,
                sku_name=str(out_item.get("sku_name") or ""),
                quantity=out_item.get("quantity"),
                reorder_point=out_item.get("reorder_point"),
                user_id=user_id,
            )
        except Exception:
            pass
    return {"ok": True, "item": out_item}


def record_stock_movement_sync(
    *,
    organization_id: int,
    inventory_item_id: int,
    quantity_delta: float | Decimal,
    movement_type: str = "ADJUST",
    reference_type: str | None = None,
    reference_id: str | None = None,
    notes: str | None = None,
    lot_batch: str | None = None,
    reason: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    iid = int(inventory_item_id)
    if oid <= 0 or iid <= 0:
        return {"ok": False, "error": "organization_id and inventory_item_id required"}
    delta = _dec(quantity_delta)
    if delta == 0:
        return {"ok": False, "error": "quantity_delta cannot be zero"}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    out_mov: dict[str, Any] | None = None
    out_item: dict[str, Any] | None = None
    with factory() as session:
        try:
            with session.begin():
                row = session.get(InventoryItem, iid)
                if row is None or int(row.organization_id) != oid:
                    raise LookupError("inventory item not found")
                new_q = _dec(row.quantity) + delta
                if new_q < 0:
                    raise ValueError("insufficient stock for this movement")
                row.quantity = new_q
                _recalc_value(row)
                mov = StockMovement(
                    organization_id=oid,
                    inventory_item_id=iid,
                    quantity_delta=delta,
                    movement_type=(movement_type or "ADJUST")[:32],
                    reference_type=(reference_type or "")[:64] or None,
                    reference_id=(reference_id or "")[:128] or None,
                    notes=notes,
                    lot_batch=(lot_batch or "").strip()[:64] or None,
                    reason=(reason or "").strip()[:256] or None,
                    created_by_user_id=user_id if user_id and user_id > 0 else None,
                )
                session.add(mov)
                session.flush()
                _mirror_legacy_delta(
                    session,
                    organization_id=oid,
                    sku_name=row.sku_name,
                    location=row.location or "",
                    delta=delta,
                )
                out_mov = _serialize_movement(mov)
                out_item = _serialize_item(row)
        except LookupError:
            return {"ok": False, "error": "inventory item not found"}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="stock_movement",
        metadata={
            "channel": "inventory_phase2.movement",
            "inventory_item_id": iid,
            "delta": float(delta),
            "movement_type": movement_type,
        },
    )
    if out_item is not None and delta < 0:
        try:
            from services.jarvis_agent_event_engine import record_inventory_quantity_event_sync

            record_inventory_quantity_event_sync(
                organization_id=oid,
                inventory_item_id=iid,
                sku_name=str(out_item.get("sku_name") or ""),
                quantity=out_item.get("quantity"),
                reorder_point=out_item.get("reorder_point"),
                user_id=user_id,
            )
        except Exception:
            pass
    return {"ok": True, "movement": out_mov, "item": out_item}


def list_low_stock_alerts_sync(
    *,
    organization_id: int,
    threshold_override: float | None = None,
) -> dict[str, Any]:
    """Items where ``reorder_point`` is set and ``quantity`` <= reorder (or override threshold)."""
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    thr = _dec(threshold_override) if threshold_override is not None else None
    alerts: list[dict[str, Any]] = []
    with factory() as session:
        rows = list(
            session.scalars(select(InventoryItem).where(InventoryItem.organization_id == oid)).all()
        )
        for r in rows:
            rp = r.reorder_point
            if rp is None:
                continue
            q = _dec(r.quantity)
            if thr is not None:
                if q <= thr:
                    alerts.append({**_serialize_item(r), "alert_reason": "below_global_threshold"})
            elif q <= _dec(rp):
                alerts.append({**_serialize_item(r), "alert_reason": "at_or_below_reorder_point"})
    return {"ok": True, "alerts": alerts}


def create_supplier_sync(
    *,
    organization_id: int,
    name: str,
    gstin: str | None = None,
    contact_email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    n = (name or "").strip()
    if not n:
        return {"ok": False, "error": "name required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        with session.begin():
            s = Supplier(
                organization_id=oid,
                name=n,
                gstin=(gstin or "").strip()[:15] or None,
                contact_email=(contact_email or "").strip() or None,
                phone=(phone or "").strip()[:32] or None,
                address=(address or "").strip() or None,
            )
            session.add(s)
            session.flush()
            sid = int(s.id)
            out = _serialize_supplier(s)
    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="supplier",
        metadata={"channel": "inventory_phase2.supplier_create", "supplier_id": sid},
    )
    return {"ok": True, "supplier": out}


def list_suppliers_sync(*, organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        rows = list(
            session.scalars(
                select(Supplier).where(Supplier.organization_id == oid).order_by(Supplier.name)
            ).all()
        )
    return {"ok": True, "suppliers": [_serialize_supplier(r) for r in rows]}


def create_purchase_order_sync(
    *,
    organization_id: int,
    supplier_id: int,
    order_date: date,
    expected_date: date | None = None,
    notes: str | None = None,
    lines: list[dict[str, Any]],
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    sid = int(supplier_id)
    if oid <= 0 or sid <= 0:
        return {"ok": False, "error": "organization_id and supplier_id required"}
    if not lines:
        return {"ok": False, "error": "lines required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    total = Decimal("0")
    parsed: list[tuple[str, Decimal, Decimal, Decimal]] = []
    for ln in lines:
        sku = (ln.get("sku_name") or "").strip()
        if not sku:
            return {"ok": False, "error": "each line needs sku_name"}
        qo = _dec(ln.get("quantity_ordered"))
        uc = _dec(ln.get("unit_cost_pre_tax"))
        if qo <= 0:
            return {"ok": False, "error": "quantity_ordered must be positive"}
        line_total = (qo * uc).quantize(Decimal("0.01"))
        total += line_total
        parsed.append((sku, qo, uc, line_total))

    out_po: dict[str, Any]
    with factory() as session:
        try:
            with session.begin():
                sup = session.get(Supplier, sid)
                if sup is None or int(sup.organization_id) != oid:
                    raise LookupError("supplier not found")
                po = PurchaseOrder(
                    organization_id=oid,
                    supplier_id=sid,
                    status="draft",
                    order_date=order_date,
                    expected_date=expected_date,
                    notes=(notes or "").strip() or None,
                    total_inr=total,
                )
                session.add(po)
                session.flush()
                pid = int(po.id)
                for sku, qo, uc, lt in parsed:
                    pl = PurchaseOrderLine(
                        purchase_order_id=pid,
                        sku_name=sku,
                        quantity_ordered=qo,
                        quantity_received=Decimal("0"),
                        unit_cost_pre_tax=uc,
                        line_total_inr=lt,
                    )
                    session.add(pl)
                out_po = {
                    "id": pid,
                    "organization_id": oid,
                    "supplier_id": sid,
                    "status": po.status,
                    "order_date": po.order_date.isoformat() if po.order_date else None,
                    "expected_date": po.expected_date.isoformat() if po.expected_date else None,
                    "total_inr": float(po.total_inr),
                    "notes": po.notes,
                }
        except LookupError:
            return {"ok": False, "error": "supplier not found"}

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="purchase_order",
        metadata={"channel": "inventory_phase2.po_create", "purchase_order_id": out_po["id"]},
    )
    return {"ok": True, "purchase_order": out_po}


def receive_purchase_order_line_sync(
    *,
    organization_id: int,
    purchase_order_id: int,
    line_id: int,
    quantity: float | Decimal,
    inventory_location: str = "",
    lot_batch: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Receive stock against a PO line: updates line, inventory item (create if needed), movement PO_RECEIPT."""
    oid = int(organization_id)
    po_id = int(purchase_order_id)
    lid = int(line_id)
    qty = _dec(quantity)
    if oid <= 0 or po_id <= 0 or lid <= 0 or qty <= 0:
        return {"ok": False, "error": "invalid ids or quantity"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    out_item: dict[str, Any]
    out_line: dict[str, Any]
    po_status: str
    with factory() as session:
        try:
            with session.begin():
                po = session.get(PurchaseOrder, po_id)
                if po is None or int(po.organization_id) != oid:
                    raise LookupError("purchase order not found")
                line = session.get(PurchaseOrderLine, lid)
                if line is None or int(line.purchase_order_id) != po_id:
                    raise LookupError("purchase order line not found")
                remain = _dec(line.quantity_ordered) - _dec(line.quantity_received)
                if qty > remain:
                    raise ValueError("receive quantity exceeds open quantity on line")
                loc = (inventory_location or "").strip()

                stmt = (
                    select(InventoryItem)
                    .where(InventoryItem.organization_id == oid)
                    .where(InventoryItem.sku_name == line.sku_name)
                    .where(InventoryItem.location == loc)
                )
                inv = session.scalars(stmt.limit(1)).first()
                if inv is None:
                    inv = InventoryItem(
                        organization_id=oid,
                        sku_name=line.sku_name,
                        location=loc,
                        quantity=Decimal("0"),
                        unit_cost_pre_tax=line.unit_cost_pre_tax,
                    )
                    session.add(inv)
                    session.flush()

                inv.quantity = _dec(inv.quantity) + qty
                if inv.unit_cost_pre_tax is None:
                    inv.unit_cost_pre_tax = line.unit_cost_pre_tax
                _recalc_value(inv)

                line.quantity_received = _dec(line.quantity_received) + qty
                lb = (lot_batch or "").strip()[:64] or None
                mov = StockMovement(
                    organization_id=oid,
                    inventory_item_id=int(inv.id),
                    quantity_delta=qty,
                    movement_type="PO_RECEIPT",
                    reference_type="purchase_order",
                    reference_id=str(po_id),
                    notes=f"line {lid}",
                    lot_batch=lb,
                    reason="PO receipt",
                    created_by_user_id=user_id if user_id and user_id > 0 else None,
                )
                session.add(mov)
                _mirror_legacy_delta(
                    session,
                    organization_id=oid,
                    sku_name=inv.sku_name,
                    location=inv.location or "",
                    delta=qty,
                )

                all_lines = list(
                    session.scalars(
                        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po_id)
                    ).all()
                )
                if all(_dec(x.quantity_received) >= _dec(x.quantity_ordered) for x in all_lines):
                    po.status = "received"
                else:
                    po.status = "partial"

                po_status = str(po.status)
                out_item = _serialize_item(inv)
                out_line = {
                    "id": lid,
                    "quantity_ordered": float(line.quantity_ordered),
                    "quantity_received": float(line.quantity_received),
                }
        except LookupError as exc:
            return {"ok": False, "error": str(exc)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="purchase_order",
        metadata={
            "channel": "inventory_phase2.po_receive",
            "purchase_order_id": po_id,
            "line_id": lid,
            "quantity": float(qty),
        },
    )
    if out_item is not None:
        try:
            from services.jarvis_agent_event_engine import record_inventory_quantity_event_sync

            record_inventory_quantity_event_sync(
                organization_id=oid,
                inventory_item_id=int(out_item.get("id") or 0),
                sku_name=str(out_item.get("sku_name") or ""),
                quantity=out_item.get("quantity"),
                reorder_point=out_item.get("reorder_point"),
                user_id=user_id,
            )
        except Exception:
            pass
    return {"ok": True, "item": out_item, "line": out_line, "purchase_order_status": po_status}


def list_stock_movements_sync(
    *,
    organization_id: int,
    limit: int = 200,
    inventory_item_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 500))
    with factory() as session:
        q = select(StockMovement).where(StockMovement.organization_id == oid)
        if inventory_item_id is not None and int(inventory_item_id) > 0:
            q = q.where(StockMovement.inventory_item_id == int(inventory_item_id))
        q = q.order_by(StockMovement.id.desc()).limit(lim)
        rows = list(session.scalars(q).all())
    return {"ok": True, "movements": [_serialize_movement(r) for r in rows]}


def list_purchase_orders_sync(*, organization_id: int, limit: int = 100) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 200))
    with factory() as session:
        pos = list(
            session.scalars(
                select(PurchaseOrder)
                .where(PurchaseOrder.organization_id == oid)
                .order_by(PurchaseOrder.id.desc())
                .limit(lim)
            ).all()
        )
        out: list[dict[str, Any]] = []
        for po in pos:
            lines = list(
                session.scalars(
                    select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == int(po.id))
                ).all()
            )
            out.append(
                {
                    "id": int(po.id),
                    "supplier_id": int(po.supplier_id),
                    "status": po.status,
                    "order_date": po.order_date.isoformat() if po.order_date else None,
                    "expected_date": po.expected_date.isoformat() if po.expected_date else None,
                    "notes": po.notes,
                    "supplier_invoice_no": getattr(po, "supplier_invoice_no", None),
                    "supplier_invoice_date": po.supplier_invoice_date.isoformat()
                    if getattr(po, "supplier_invoice_date", None)
                    else None,
                    "total_inr": float(po.total_inr or 0),
                    "lines": [
                        {
                            "id": int(ln.id),
                            "sku_name": ln.sku_name,
                            "quantity_ordered": float(ln.quantity_ordered),
                            "quantity_received": float(ln.quantity_received),
                            "unit_cost_pre_tax": float(ln.unit_cost_pre_tax),
                            "line_total_inr": float(ln.line_total_inr or 0),
                        }
                        for ln in lines
                    ],
                }
            )
    return {"ok": True, "purchase_orders": out}


def update_purchase_order_supplier_invoice_sync(
    *,
    organization_id: int,
    purchase_order_id: int,
    supplier_invoice_no: str | None = None,
    supplier_invoice_date: date | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    pid = int(purchase_order_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        with session.begin():
            po = session.get(PurchaseOrder, pid)
            if po is None or int(po.organization_id) != oid:
                return {"ok": False, "error": "purchase order not found"}
            if supplier_invoice_no is not None:
                po.supplier_invoice_no = (supplier_invoice_no or "").strip()[:256] or None
            if supplier_invoice_date is not None:
                po.supplier_invoice_date = supplier_invoice_date
    system_audit.record_system_audit(
        action=system_audit.ACTION_STOCK_UPDATE,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="purchase_order",
        metadata={"channel": "inventory_phase2.po_supplier_invoice", "purchase_order_id": pid},
    )
    return {"ok": True}


def record_supplier_payment_sync(
    *,
    organization_id: int,
    supplier_id: int,
    amount_inr: float | Decimal,
    purchase_order_id: int | None = None,
    method: str = "bank",
    reference: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    sid = int(supplier_id)
    amt = _dec(amount_inr)
    if oid <= 0 or sid <= 0 or amt <= 0:
        return {"ok": False, "error": "invalid organization, supplier, or amount"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    pid = int(purchase_order_id) if purchase_order_id is not None and int(purchase_order_id) > 0 else None
    pay_id = 0
    with factory() as session:
        with session.begin():
            sup = session.get(Supplier, sid)
            if sup is None or int(sup.organization_id) != oid:
                return {"ok": False, "error": "supplier not found"}
            if pid is not None:
                po = session.get(PurchaseOrder, pid)
                if po is None or int(po.organization_id) != oid:
                    return {"ok": False, "error": "purchase order not found"}
            row = SupplierPayment(
                organization_id=oid,
                supplier_id=sid,
                purchase_order_id=pid,
                amount_inr=amt,
                method=(method or "bank")[:32],
                reference=(reference or "").strip() or None,
                notes=(notes or "").strip() or None,
            )
            session.add(row)
            session.flush()
            pay_id = int(row.id)
    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=oid,
        user_id=user_id if user_id and int(user_id) > 0 else None,
        resource_type="supplier_payment",
        metadata={"channel": "inventory_phase2.supplier_payment", "payment_id": pay_id},
    )
    return {"ok": True, "payment_id": pay_id}


def list_supplier_payments_sync(*, organization_id: int, limit: int = 100) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 300))
    with factory() as session:
        rows = list(
            session.scalars(
                select(SupplierPayment)
                .where(SupplierPayment.organization_id == oid)
                .order_by(SupplierPayment.id.desc())
                .limit(lim)
            ).all()
        )
    items = [
        {
            "id": int(r.id),
            "supplier_id": int(r.supplier_id),
            "purchase_order_id": int(r.purchase_order_id) if r.purchase_order_id else None,
            "amount_inr": float(r.amount_inr),
            "method": r.method,
            "reference": r.reference,
            "notes": r.notes,
            "paid_at": r.paid_at.isoformat() if r.paid_at else None,
        }
        for r in rows
    ]
    return {"ok": True, "payments": items}
