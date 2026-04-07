"""Digital twin, empire lab, and vault media serving."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated

import asset_portal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user, require_roles
from services import billing_guard, project_engine
from factory.machine_sensor import apply_control, tick_and_get_live_status
from services.financial_analytics import aggregate_empire_financial_summary

router = APIRouter(tags=["Factory & Digital Twin"])


def _media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".txt":
        return "text/plain; charset=utf-8"
    if ext == ".md":
        return "text/markdown; charset=utf-8"
    if ext == ".csv":
        return "text/csv; charset=utf-8"
    return "application/octet-stream"


@router.get("/empire/financial-summary")
async def empire_financial_summary(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    """Aggregated revenue (invoices), outstanding debt principal, production labor costs — org-scoped."""
    try:
        payload = aggregate_empire_financial_summary(organization_id=_user.organization_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Financial aggregation failed: {type(exc).__name__}: {exc}",
        ) from exc
    return JSONResponse(content=payload)


@router.get("/empire/lab-status")
async def empire_lab_status(
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    """Scrap inventory + robot training + fabrication queue (Empire Vision)."""
    _ = _user
    from factory.fab_engine import fabrication_dashboard_payload
    from factory.robot_training_sim import read_last_training_run
    from factory.scrap_engine import load_inventory

    return JSONResponse(
        content={
            "scrap_inventory": load_inventory(),
            "robot_training": read_last_training_run(),
            "fabrication": fabrication_dashboard_payload(),
        }
    )


@router.get("/factory/live-status")
async def factory_live_status(
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    """Digital Twin: simulated sensors + stage LEDs; polls every ~5s from dashboard."""
    _ = _user
    return JSONResponse(content=tick_and_get_live_status())


@router.get("/factory/status")
async def factory_status_v2(
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    """Phase 6 — equipment registry, open work orders, manpower load, billing hold (JSON for dashboards + JARVIS)."""
    from services.factory_status_service import build_factory_status_v2

    return JSONResponse(content=build_factory_status_v2(_user.organization_id))


class EquipmentStatusBody(BaseModel):
    status: str = Field(..., description="Running | Down | Maintenance")


@router.patch("/factory/os/equipment/{equipment_id}/status")
async def factory_equipment_set_status(
    equipment_id: int,
    body: EquipmentStatusBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    """Set equipment status; **Down** triggers org-level factory billing pause (see billing_guard)."""
    from services.maintenance_service import normalize_equipment_status, set_equipment_status

    ok, msg = set_equipment_status(
        organization_id=_user.organization_id,
        equipment_id=equipment_id,
        new_status=body.status,
    )
    if not ok:
        raise HTTPException(status_code=400 if msg != "database_unavailable" else 503, detail=msg)
    return JSONResponse(
        content={
            "status": "ok",
            "equipment_id": equipment_id,
            "normalized_status": normalize_equipment_status(body.status),
        }
    )


class TwinControlBody(BaseModel):
    operator_running: bool | None = None
    hydraulic_fixed: bool | None = None
    maintenance_mode: bool | None = None


class FactoryProjectCreateBody(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=500)
    current_stage: int = Field(..., ge=2, le=4, description="2=income, 3=repair, 4=expansion")
    priority: int = 0
    asset_id: int | None = Field(default=None, ge=1)
    revival_cost_inr: float | None = Field(default=None, ge=0)


class FactoryAssignStaffBody(BaseModel):
    user_id: int = Field(..., ge=1)
    role_note: str = Field(default="", max_length=500)


class FactoryRevivalCostBody(BaseModel):
    revival_cost_inr: float = Field(..., ge=0)


@router.get("/factory/os/billing-hold")
async def factory_os_billing_hold_status(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    oid = _user.organization_id
    return JSONResponse(
        content={
            "organization_id": oid,
            "billing_paused": billing_guard.is_billing_paused(oid),
            "detail": billing_guard.billing_pause_message(oid) or None,
        }
    )


@router.post("/factory/os/billing-hold/clear")
async def factory_os_billing_hold_clear(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    billing_guard.set_factory_billing_paused(_user.organization_id, False, reason="")
    return JSONResponse(content={"status": "ok", "billing_paused": False})


@router.get("/factory/os/projects")
async def factory_os_list_projects(
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    rows = project_engine.list_projects(_user.organization_id)
    items = [
        {
            "id": int(p.id),
            "project_name": p.project_name,
            "current_stage": int(p.current_stage),
            "stage_label": project_engine.stage_label(int(p.current_stage)),
            "status": p.status,
            "priority": int(p.priority),
            "asset_id": int(p.asset_id) if p.asset_id is not None else None,
            "revival_cost_inr": float(p.revival_cost_inr) if p.revival_cost_inr is not None else None,
            "machine_failed": bool(p.machine_failed),
        }
        for p in rows
    ]
    return JSONResponse(content={"items": items})


@router.post("/factory/os/projects")
async def factory_os_create_project(
    body: FactoryProjectCreateBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    rc = Decimal(str(body.revival_cost_inr)) if body.revival_cost_inr is not None else None
    pid = project_engine.create_project(
        organization_id=_user.organization_id,
        project_name=body.project_name,
        current_stage=body.current_stage,
        priority=body.priority,
        asset_id=body.asset_id,
        revival_cost_inr=rc,
    )
    if pid is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    return JSONResponse(content={"id": pid, "status": "created"})


@router.patch("/factory/os/projects/{project_id}/revival-cost")
async def factory_os_set_revival_cost(
    project_id: int,
    body: FactoryRevivalCostBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    rows = project_engine.list_projects(_user.organization_id)
    if not any(int(p.id) == int(project_id) for p in rows):
        raise HTTPException(status_code=404, detail="project not found")
    ok = project_engine.set_revival_cost(int(project_id), Decimal(str(body.revival_cost_inr)))
    if not ok:
        raise HTTPException(status_code=503, detail="update failed")
    return JSONResponse(content={"status": "ok"})


@router.post("/factory/os/projects/{project_id}/machine-failure")
async def factory_os_stage2_machine_failure(
    project_id: int,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    ok, msg = project_engine.apply_stage2_machine_failure(
        project_stage_id=int(project_id),
        organization_id=_user.organization_id,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return JSONResponse(content={"status": "ok", "billing_paused": True})


@router.post("/factory/os/projects/{project_id}/clear-failure")
async def factory_os_clear_stage2_failure(
    project_id: int,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    ok, msg = project_engine.clear_stage2_machine_failure(
        project_stage_id=int(project_id),
        organization_id=_user.organization_id,
        resume_billing=True,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return JSONResponse(content={"status": "ok", "machine_failed": False})


@router.post("/factory/os/projects/{project_id}/assign")
async def factory_os_assign_staff(
    project_id: int,
    body: FactoryAssignStaffBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    ok, msg = project_engine.assign_staff(
        project_stage_id=int(project_id),
        organization_id=_user.organization_id,
        user_id=int(body.user_id),
        role_note=body.role_note,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return JSONResponse(content={"status": "ok", "detail": msg})


@router.post("/factory/twin-control")
async def factory_twin_control(
    body: TwinControlBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    """Start/Stop, hydraulic fixed flag, maintenance mode — persisted to vault JSON."""
    _ = _user
    apply_control(
        operator_running=body.operator_running,
        hydraulic_fixed=body.hydraulic_fixed,
        maintenance_mode=body.maintenance_mode,
    )
    return JSONResponse(content=tick_and_get_live_status())


@router.get("/media/vault/{path:path}")
def serve_vault_file(
    path: str,
    _user: Annotated[CurrentUser, Depends(get_current_user)],
) -> FileResponse:
    """
    Serve vault files with extension whitelist (no JSON secrets).
    Path uses forward slashes (URL-encoded segments OK).
    """
    resolved = asset_portal.resolve_vault_file(path)
    if resolved is None:
        raise HTTPException(status_code=404, detail="File not found or not allowed")
    return FileResponse(
        resolved,
        filename=resolved.name,
        media_type=_media_type(resolved),
    )
