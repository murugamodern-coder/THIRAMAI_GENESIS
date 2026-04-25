"""Business module APIs: inventory + invoice with role-scoped visibility."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_any_role, require_staff
from services.billing_phase2_service import create_structured_invoice_sync, list_invoices_sync
from services.inventory_phase2_service import create_inventory_item_sync, list_inventory_items_sync

router = APIRouter(prefix="/business", tags=["Business Module"])


def _is_owner_scope(user: CurrentUser) -> bool:
    return user.role_name.lower() in {"owner", "admin", "manager"}


def _staff_marker(user_id: int) -> str:
    return f"business_module:user:{int(user_id)}"


def _matches_staff_marker(value: str | None, user_id: int) -> bool:
    v = (value or "").strip().lower()
    return _staff_marker(user_id).lower() in v


class BusinessInventoryCreateBody(BaseModel):
    sku_name: str = Field(..., min_length=1, max_length=256)
    quantity: float = Field(0, ge=0)
    location: str = Field(default="", max_length=256)
    unit: str = Field(default="", max_length=64)
    unit_price: float | None = Field(None, ge=0)
    reorder_point: float | None = Field(None, ge=0)
    hsn_code: str | None = Field(default=None, max_length=64)


class BusinessInvoiceLine(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    quantity: float = Field(..., gt=0)
    unit_price_pre_tax: float = Field(..., ge=0)
    gst_rate_percent: float = Field(18.0, ge=0)
    hsn_code: str | None = Field(default=None, max_length=64)


class BusinessInvoiceCreateBody(BaseModel):
    invoice_no: str = Field(default="", max_length=128)
    invoice_date: str = Field("", description="YYYY-MM-DD; optional")
    lines: list[BusinessInvoiceLine] = Field(..., min_length=1, max_length=100)


@router.get("/inventory", summary="Business inventory list (owner full, staff own records)")
async def business_inventory(
    limit: int = Query(200, ge=1, le=500),
    user: CurrentUser = Depends(require_any_role),
) -> dict[str, Any]:
    out = list_inventory_items_sync(
        organization_id=user.organization_id,
        limit=limit,
        offset=0,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "inventory unavailable")

    items = out.get("items") or []
    if not _is_owner_scope(user):
        items = [it for it in items if _matches_staff_marker(it.get("external_ref"), user.id)]

    return {
        "ok": True,
        "inventory": items,
        "erp_summary": {
            "total_items_visible": len(items),
            "scope": "full" if _is_owner_scope(user) else "staff_own_data",
        },
    }


@router.post("/inventory", summary="Create inventory item (staff scoped to own records)")
async def business_inventory_create(
    body: BusinessInventoryCreateBody,
    user: CurrentUser = Depends(require_staff),
) -> dict[str, Any]:
    out = create_inventory_item_sync(
        organization_id=user.organization_id,
        sku_name=body.sku_name,
        quantity=body.quantity,
        location=body.location,
        unit=body.unit,
        unit_price=body.unit_price,
        reorder_point=body.reorder_point,
        hsn_code=body.hsn_code,
        external_ref=_staff_marker(user.id),
        user_id=user.id if user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create failed")
    return out


@router.get("/invoice", summary="Business invoices (owner full, staff own records)")
async def business_invoice(
    limit: int = Query(100, ge=1, le=500),
    user: CurrentUser = Depends(require_any_role),
) -> dict[str, Any]:
    out = list_invoices_sync(organization_id=user.organization_id, limit=limit)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "invoice list unavailable")

    invoices = out.get("invoices") or []
    if not _is_owner_scope(user):
        invoices = [inv for inv in invoices if _matches_staff_marker(inv.get("external_ref"), user.id)]

    total = sum(Decimal(str(x.get("grand_total_inr") or 0)) for x in invoices)
    return {
        "ok": True,
        "invoices": invoices,
        "erp_summary": {
            "invoice_count_visible": len(invoices),
            "grand_total_visible_inr": float(total.quantize(Decimal("0.01")) if invoices else Decimal("0")),
            "scope": "full" if _is_owner_scope(user) else "staff_own_data",
        },
    }


@router.post("/invoice", summary="Create invoice (basic ERP billing)")
async def business_invoice_create(
    body: BusinessInvoiceCreateBody,
    user: CurrentUser = Depends(require_staff),
) -> dict[str, Any]:
    from datetime import date

    invoice_date = None
    raw = (body.invoice_date or "").strip()
    if raw:
        try:
            y, m, d = raw.split("-")
            invoice_date = date(int(y), int(m), int(d))
        except Exception:
            raise HTTPException(status_code=400, detail="invoice_date must be YYYY-MM-DD") from None

    out = create_structured_invoice_sync(
        organization_id=user.organization_id,
        invoice_no=(body.invoice_no or "").strip(),
        invoice_date=invoice_date,
        lines=[ln.model_dump() for ln in body.lines],
        external_ref=_staff_marker(user.id),
        user_id=user.id if user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "invoice create failed")
    return out

