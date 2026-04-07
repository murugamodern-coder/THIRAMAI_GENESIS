"""Phase 2 production: logs, machine status, maintenance, raw material consumption."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from core.rbac import Permission
from services.production_phase2_service import (
    create_maintenance_log_sync,
    create_production_log_sync,
    list_machines_sync,
    production_summary_sync,
)

router = APIRouter(tags=["Production"])


def _parse_date(s: str | None) -> date | None:
    if not (s or "").strip():
        return None
    try:
        parts = s.strip().split("-")
        if len(parts) != 3:
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


class RawConsumptionBody(BaseModel):
    raw_material_id: int = Field(..., ge=1)
    quantity: float = Field(..., gt=0)


class ProductionLogBody(BaseModel):
    asset_id: int = Field(..., ge=1)
    production_unit: str = "general"
    cement_in: float | None = None
    sand_in: float | None = None
    blocks_out: float | None = None
    raw_material_in: float | None = None
    yield_out: float | None = None
    labor_cost: float | None = Field(None, ge=0)
    external_ref: str | None = None
    raw_consumptions: list[RawConsumptionBody] | None = None


@router.post("/production/log")
async def production_create_log(
    body: ProductionLogBody,
    _user: CurrentUser = Depends(require_permission(Permission.PRODUCTION_WRITE)),
) -> JSONResponse:
    rcs = None
    if body.raw_consumptions:
        rcs = [x.model_dump() for x in body.raw_consumptions]
    out = create_production_log_sync(
        organization_id=_user.organization_id,
        asset_id=body.asset_id,
        production_unit=body.production_unit,
        cement_in=body.cement_in,
        sand_in=body.sand_in,
        blocks_out=body.blocks_out,
        raw_material_in=body.raw_material_in,
        yield_out=body.yield_out,
        labor_cost=body.labor_cost,
        external_ref=body.external_ref,
        raw_consumptions=rcs,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "log failed")
    return JSONResponse(content=out)


@router.get("/production/summary")
async def production_summary(
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
    _user: CurrentUser = Depends(require_permission(Permission.PRODUCTION_READ)),
) -> JSONResponse:
    sd = _parse_date(start_date)
    ed = _parse_date(end_date)
    out = production_summary_sync(
        organization_id=_user.organization_id,
        start_date=sd,
        end_date=ed,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "summary failed")
    return JSONResponse(content=out)


@router.get("/production/machines")
async def production_list_machines(
    _user: CurrentUser = Depends(require_permission(Permission.PRODUCTION_READ)),
) -> JSONResponse:
    out = list_machines_sync(organization_id=_user.organization_id)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return JSONResponse(content=out)


class MaintenanceBody(BaseModel):
    equipment_id: int = Field(..., ge=1)
    issue_description: str = Field(..., min_length=1)
    cost: float = Field(0, ge=0)
    technician_name: str | None = None


@router.post("/production/maintenance")
async def production_maintenance(
    body: MaintenanceBody,
    _user: CurrentUser = Depends(require_permission(Permission.PRODUCTION_WRITE)),
) -> JSONResponse:
    out = create_maintenance_log_sync(
        organization_id=_user.organization_id,
        equipment_id=body.equipment_id,
        issue_description=body.issue_description,
        cost=body.cost,
        technician_name=body.technician_name,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "maintenance failed")
    return JSONResponse(content=out)
