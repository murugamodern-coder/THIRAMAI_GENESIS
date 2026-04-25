"""Asset portal listing and financial summary (inventory / vault index context)."""

from __future__ import annotations

import asyncio
from datetime import date

import asset_portal
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user, require_any_role, require_staff
from services.financial_service import financial_performance_summary_for_organization
from services.usage_log_service import ACTION_INVENTORY_CREATE, ACTION_INVENTORY_UPDATE, log_usage_sync
from services.inventory_service import (
    add_inventory_sync,
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
from services.sale_execution import execute_sell_stock_sync
from services.automation_rule_engine import evaluate_rules

router = APIRouter(tags=["Inventory & Assets"])


def _parse_date(s: str | None) -> date | None:
    if not (s or "").strip():
        return None
    parts = s.strip().split("-")
    if len(parts) != 3:
        return None
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, m, d)


# --- Phase 2: enterprise inventory (RBAC: inventory.read / inventory.write) ---


@router.get("/inventory")
async def inventory_list_v2(
    limit: int = Query(500, ge=1, le=500, description="Page size (max 500)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    out = await asyncio.to_thread(
        list_inventory_items_sync,
        organization_id=_user.organization_id,
        limit=limit,
        offset=offset,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return JSONResponse(content=out)


class InventoryItemCreateBody(BaseModel):
    sku_name: str = Field(..., min_length=1)
    location: str = ""
    unit: str = ""
    quantity: float = Field(0, ge=0)
    unit_price: float | None = Field(None, ge=0)
    unit_cost_pre_tax: float | None = Field(None, ge=0)
    gst_rate_percent: float | None = Field(None, ge=0)
    hsn_code: str | None = None
    external_ref: str | None = None
    reorder_point: float | None = Field(None, ge=0)


@router.post("/inventory/item")
async def inventory_create_item(
    body: InventoryItemCreateBody,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    out = create_inventory_item_sync(
        organization_id=_user.organization_id,
        sku_name=body.sku_name,
        location=body.location,
        quantity=body.quantity,
        unit_price=body.unit_price,
        unit_cost_pre_tax=body.unit_cost_pre_tax,
        gst_rate_percent=body.gst_rate_percent,
        hsn_code=body.hsn_code,
        external_ref=body.external_ref,
        reorder_point=body.reorder_point,
        unit=body.unit,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create failed")
    item = out.get("item") or {}
    await asyncio.to_thread(
        lambda: log_usage_sync(
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            action=ACTION_INVENTORY_CREATE,
            metadata={"item_id": item.get("id"), "sku_name": item.get("sku_name")},
        ),
    )
    await asyncio.to_thread(
        evaluate_rules,
        {
            "user_id": int(_user.id),
            "organization_id": int(_user.organization_id),
            "role_name": str(_user.role_name or ""),
            "trigger_type": "inventory_updated",
            "payload": {
                "item_id": item.get("id"),
                "sku_name": item.get("sku_name"),
                "quantity": item.get("quantity"),
                "reorder_point": item.get("reorder_point"),
            },
        },
    )
    return JSONResponse(content=out)


class InventoryItemUpdateBody(BaseModel):
    sku_name: str | None = None
    location: str | None = None
    unit: str | None = None
    quantity: float | None = Field(None, ge=0)
    unit_price: float | None = Field(None, ge=0)
    unit_cost_pre_tax: float | None = Field(None, ge=0)
    gst_rate_percent: float | None = Field(None, ge=0)
    hsn_code: str | None = None
    external_ref: str | None = None
    reorder_point: float | None = Field(None, ge=0)


@router.put("/inventory/item/{item_id}")
async def inventory_update_item(
    item_id: int = Path(..., ge=1),
    body: InventoryItemUpdateBody | None = None,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    b = body or InventoryItemUpdateBody()
    out = update_inventory_item_sync(
        organization_id=_user.organization_id,
        item_id=item_id,
        sku_name=b.sku_name,
        location=b.location,
        unit=b.unit,
        quantity=b.quantity,
        unit_price=b.unit_price,
        unit_cost_pre_tax=b.unit_cost_pre_tax,
        gst_rate_percent=b.gst_rate_percent,
        hsn_code=b.hsn_code,
        external_ref=b.external_ref,
        reorder_point=b.reorder_point,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "update failed")
    item = out.get("item") or {}
    await asyncio.to_thread(
        lambda: log_usage_sync(
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            action=ACTION_INVENTORY_UPDATE,
            metadata={"item_id": item_id, "sku_name": item.get("sku_name")},
        ),
    )
    await asyncio.to_thread(
        evaluate_rules,
        {
            "user_id": int(_user.id),
            "organization_id": int(_user.organization_id),
            "role_name": str(_user.role_name or ""),
            "trigger_type": "inventory_updated",
            "payload": {
                "item_id": item_id,
                "sku_name": item.get("sku_name"),
                "quantity": item.get("quantity"),
                "reorder_point": item.get("reorder_point"),
            },
        },
    )
    return JSONResponse(content=out)


class StockMovementBody(BaseModel):
    inventory_item_id: int = Field(..., ge=1)
    quantity_delta: float = Field(..., description="Positive = in, negative = out")
    movement_type: str = "ADJUST"
    reference_type: str | None = None
    reference_id: str | None = None
    notes: str | None = None
    lot_batch: str | None = None
    reason: str | None = None


@router.post("/inventory/movement")
async def inventory_movement(
    body: StockMovementBody,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    out = record_stock_movement_sync(
        organization_id=_user.organization_id,
        inventory_item_id=body.inventory_item_id,
        quantity_delta=body.quantity_delta,
        movement_type=body.movement_type,
        reference_type=body.reference_type,
        reference_id=body.reference_id,
        notes=body.notes,
        lot_batch=body.lot_batch,
        reason=body.reason,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "movement failed")
    row = out.get("movement") or {}
    await asyncio.to_thread(
        evaluate_rules,
        {
            "user_id": int(_user.id),
            "organization_id": int(_user.organization_id),
            "role_name": str(_user.role_name or ""),
            "trigger_type": "inventory_updated",
            "payload": {
                "item_id": body.inventory_item_id,
                "quantity_delta": body.quantity_delta,
                "movement_type": body.movement_type,
                "quantity": row.get("quantity_after"),
            },
        },
    )
    return JSONResponse(content=out)


@router.get("/inventory/movements")
async def inventory_movements_list(
    limit: int = Query(200, ge=1, le=500),
    inventory_item_id: int | None = Query(None, ge=1),
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    out = list_stock_movements_sync(
        organization_id=_user.organization_id,
        limit=limit,
        inventory_item_id=inventory_item_id,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return JSONResponse(content=out)


@router.get("/inventory/alerts")
async def inventory_alerts(
    threshold: float | None = Query(None, ge=0, description="Optional global qty threshold"),
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    out = list_low_stock_alerts_sync(
        organization_id=_user.organization_id,
        threshold_override=threshold,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "alerts failed")
    return JSONResponse(content=out)


class SupplierCreateBody(BaseModel):
    name: str = Field(..., min_length=1)
    gstin: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    address: str | None = None


@router.post("/inventory/supplier")
async def inventory_create_supplier(
    body: SupplierCreateBody,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    out = create_supplier_sync(
        organization_id=_user.organization_id,
        name=body.name,
        gstin=body.gstin,
        contact_email=body.contact_email,
        phone=body.phone,
        address=body.address,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "supplier create failed")
    return JSONResponse(content=out)


@router.get("/inventory/suppliers")
async def inventory_list_suppliers(
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    out = list_suppliers_sync(organization_id=_user.organization_id)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list suppliers failed")
    return JSONResponse(content=out)


class POLineIn(BaseModel):
    sku_name: str = Field(..., min_length=1)
    quantity_ordered: float = Field(..., gt=0)
    unit_cost_pre_tax: float = Field(..., ge=0)


class PurchaseOrderCreateBody(BaseModel):
    supplier_id: int = Field(..., ge=1)
    order_date: str = Field(..., description="YYYY-MM-DD")
    expected_date: str | None = None
    notes: str | None = None
    lines: list[POLineIn] = Field(..., min_length=1)


@router.post("/inventory/purchase-order")
async def inventory_create_po(
    body: PurchaseOrderCreateBody,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    od = _parse_date(body.order_date)
    if od is None:
        raise HTTPException(status_code=400, detail="invalid order_date (use YYYY-MM-DD)")
    ed = _parse_date(body.expected_date) if body.expected_date else None
    out = create_purchase_order_sync(
        organization_id=_user.organization_id,
        supplier_id=body.supplier_id,
        order_date=od,
        expected_date=ed,
        notes=body.notes,
        lines=[ln.model_dump() for ln in body.lines],
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "PO create failed")
    return JSONResponse(content=out)


class POReceiveBody(BaseModel):
    line_id: int = Field(..., ge=1)
    quantity: float = Field(..., gt=0)
    inventory_location: str = ""
    lot_batch: str | None = None


@router.post("/inventory/purchase-order/{po_id}/receive-line")
async def inventory_receive_po_line(
    po_id: int = Path(..., ge=1),
    body: POReceiveBody = ...,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    out = receive_purchase_order_line_sync(
        organization_id=_user.organization_id,
        purchase_order_id=po_id,
        line_id=body.line_id,
        quantity=body.quantity,
        inventory_location=body.inventory_location,
        lot_batch=body.lot_batch,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "receive failed")
    return JSONResponse(content=out)


@router.get("/inventory/purchase-orders")
async def inventory_purchase_orders_list(
    limit: int = Query(100, ge=1, le=200),
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    out = list_purchase_orders_sync(organization_id=_user.organization_id, limit=limit)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return JSONResponse(content=out)


class POSupplierInvoiceBody(BaseModel):
    supplier_invoice_no: str | None = None
    supplier_invoice_date: str | None = Field(None, description="YYYY-MM-DD")


@router.patch("/inventory/purchase-order/{po_id}/supplier-invoice")
async def inventory_po_supplier_invoice(
    po_id: int = Path(..., ge=1),
    body: POSupplierInvoiceBody | None = None,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    b = body or POSupplierInvoiceBody()
    inv_date = _parse_date(b.supplier_invoice_date) if b.supplier_invoice_date else None
    out = update_purchase_order_supplier_invoice_sync(
        organization_id=_user.organization_id,
        purchase_order_id=po_id,
        supplier_invoice_no=b.supplier_invoice_no,
        supplier_invoice_date=inv_date,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "update failed")
    return JSONResponse(content=out)


class SupplierPaymentBody(BaseModel):
    supplier_id: int = Field(..., ge=1)
    amount_inr: float = Field(..., gt=0)
    purchase_order_id: int | None = Field(None, ge=1)
    method: str = "bank"
    reference: str | None = None
    notes: str | None = None


@router.post("/inventory/supplier-payment")
async def inventory_supplier_payment(
    body: SupplierPaymentBody,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    out = record_supplier_payment_sync(
        organization_id=_user.organization_id,
        supplier_id=body.supplier_id,
        amount_inr=body.amount_inr,
        purchase_order_id=body.purchase_order_id,
        method=body.method,
        reference=body.reference,
        notes=body.notes,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "payment failed")
    return JSONResponse(content=out)


@router.get("/inventory/supplier-payments")
async def inventory_supplier_payments_list(
    limit: int = Query(100, ge=1, le=300),
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    out = list_supplier_payments_sync(organization_id=_user.organization_id, limit=limit)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return JSONResponse(content=out)


class InventoryAddBody(BaseModel):
    """Add stock for a SKU (org-scoped; audited)."""

    sku_name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    location: str = ""
    unit_price: float | None = Field(None, ge=0, description="Optional; updates row valuation when set")


class RetailSellBody(BaseModel):
    """POS-style retail sell; policy + audit run before stock mutation."""

    sku_name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    location: str = ""
    interstate_gst: bool = False


@router.post("/inventory/add")
async def inventory_add(
    body: InventoryAddBody,
    _user: CurrentUser = Depends(require_staff),
) -> JSONResponse:
    """Increase on-hand quantity for a SKU (creates row if needed)."""
    out = add_inventory_sync(
        organization_id=_user.organization_id,
        sku_name=body.sku_name,
        quantity=body.quantity,
        location=body.location,
        unit_price=body.unit_price,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "add_inventory failed")
    return JSONResponse(content=out)


@router.post("/inventory/retail-sell")
async def retail_sell(
    request: Request,
    body: RetailSellBody,
    _user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """
    Deduct stock and create a bill after policy evaluation (``inventory.sell_stock``).

    **403** if policy **BLOCK** (e.g. customer role). **202** if policy **PROPOSE** (pending approval path).
    """
    cid = getattr(request.state, "correlation_id", None)
    correlation_id = cid if isinstance(cid, str) else None
    try:
        result = execute_sell_stock_sync(
            organization_id=_user.organization_id,
            sku_name=body.sku_name,
            quantity=float(body.quantity),
            location=(body.location or "").strip(),
            interstate_gst=body.interstate_gst,
            principal_user_id=_user.id if _user.id > 0 else None,
            principal_role_level=int(_user.role_level),
            correlation_id=correlation_id,
        )
    except HTTPException:
        raise
    try:
        from services.ltm_hooks import record_inventory_sell_execution

        record_inventory_sell_execution(
            organization_id=_user.organization_id,
            prompt_context=f"API retail-sell org={_user.organization_id}",
            sku_name=body.sku_name,
            quantity=float(body.quantity),
            location=(body.location or "").strip(),
            result=result,
            correlation_id=correlation_id,
        )
    except Exception:
        pass
    if result.get("policy") == "PROPOSE":
        return JSONResponse(
            status_code=202,
            content={
                "ok": False,
                "policy": "PROPOSE",
                "pending_approval": True,
                "detail": result.get("detail"),
                "tool_id": result.get("tool_id"),
                "message": result.get("message"),
            },
        )
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error") or "Retail sell failed",
        )
    return JSONResponse(content=result)


@router.get("/assets")
async def list_assets(
    q: str | None = Query(None, description="Filter by keyword (e.g. HDPE, Invoice)"),
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    """List indexed factory files and tenant vault files for the JWT organization only."""
    _ = _user
    items = asset_portal.list_assets_for_organization(_user.organization_id, q)
    return JSONResponse(content={"items": items, "count": len(items)})


@router.get("/assets/financial-summary")
async def financial_summary(
    _user: CurrentUser = Depends(require_any_role),
) -> JSONResponse:
    """Performance metrics from master_index.csv + vault signals + DB interest (tenant-scoped)."""
    _ = _user
    return JSONResponse(
        content=financial_performance_summary_for_organization(_user.organization_id)
    )
