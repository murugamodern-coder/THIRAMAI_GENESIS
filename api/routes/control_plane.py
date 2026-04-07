from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user, require_roles
from api.routes.billing import resolve_approval_action
from core.database import get_session_factory
from core.db.models import ControlPlaneAlert, ControlPlaneJob

router = APIRouter(tags=["Control plane"])


class MissionResolveBody(BaseModel):
    id: int = Field(..., description="AiDecision id")
    status: Literal["approved", "rejected"] = "approved"


@router.post("/mission/resolve")
async def mission_resolve_alias(
    body: MissionResolveBody,
    request: Request,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "admin", "staff")),
) -> dict[str, Any]:
    """
    Control-plane alias for mission resolution.

    Canonical route is: POST /chat/decision/{id}/resolve
    """
    from api.routes.ai_chat import resolve_decision  # local import to avoid circulars

    return await resolve_decision(body.id, {"status": body.status}, request=request, _user=_user)  # type: ignore[arg-type]


class InventoryReorderBody(BaseModel):
    item_name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)


@router.post("/inventory/reorder")
def inventory_reorder(
    body: InventoryReorderBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "admin", "staff")),
) -> dict[str, Any]:
    """
    Minimal control-plane reorder endpoint.

    Canonical inventory API is /inventory/item (create/update). This endpoint records a reorder alert row
    (does not mutate stock-on-hand accounting unless the inventory service models inbound stock explicitly).
    """
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        alert = ControlPlaneAlert(
            organization_id=_user.organization_id,
            type="inventory_reorder",
            message=f"Reorder requested: {body.item_name} (+{body.quantity})",
            severity="warning",
            resolved=False,
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return {"ok": True, "alert_id": int(alert.id)}


class InvoiceApproveBody(BaseModel):
    approval_id: str = Field(..., description="Approval UUID from /billing/invoice or /actions/brain-intent/queue")
    confirm: str = Field("YES", description='Type YES exactly (sovereign confirm) to approve high-risk action')
    feedback: Optional[str] = Field(None)


@router.post("/invoice/approve")
async def invoice_approve(
    body: InvoiceApproveBody,
    request: Request,
    background_tasks: BackgroundTasks,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, Any]:
    """
    Control-plane alias for invoice approval.

    Canonical route is: POST /actions/approvals/{approval_id}/resolve
    """
    return (await resolve_approval_action(request, body.approval_id, body, background_tasks, _user)).body  # type: ignore[return-value]


class JobCreateBody(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    payload: Optional[dict[str, Any]] = None
    scheduled_at: Optional[str] = None  # ISO8601


@router.post("/jobs")
def create_job(
    body: JobCreateBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    when = None
    if body.scheduled_at:
        when = datetime.fromisoformat(body.scheduled_at)
    with factory() as session:
        row = ControlPlaneJob(
            organization_id=_user.organization_id,
            type=body.type,
            payload=body.payload or {},
            status="scheduled",
            scheduled_at=when,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "id": int(row.id)}


@router.get("/jobs")
def list_jobs(
    limit: int = 100,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, Any]:
    from sqlalchemy import desc, select

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    limit = max(1, min(500, int(limit)))
    with factory() as session:
        stmt = (
            select(ControlPlaneJob)
            .where(ControlPlaneJob.organization_id == _user.organization_id)
            .order_by(desc(ControlPlaneJob.created_at))
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        return {
            "ok": True,
            "items": [
                {
                    "id": int(r.id),
                    "type": r.type,
                    "status": r.status,
                    "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "last_error": r.last_error,
                }
                for r in rows
            ],
        }


class AlertCreateBody(BaseModel):
    type: str
    message: str
    severity: str = "warning"


@router.post("/alerts")
def create_alert(
    body: AlertCreateBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "admin", "staff")),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        row = ControlPlaneAlert(
            organization_id=_user.organization_id,
            type=body.type,
            message=body.message,
            severity=body.severity,
            resolved=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "id": int(row.id)}


@router.get("/alerts")
def list_alerts(
    resolved: Optional[bool] = None,
    limit: int = 200,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from sqlalchemy import desc, select

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    limit = max(1, min(500, int(limit)))
    with factory() as session:
        stmt = select(ControlPlaneAlert).where(ControlPlaneAlert.organization_id == _user.organization_id)
        if resolved is not None:
            stmt = stmt.where(ControlPlaneAlert.resolved == bool(resolved))
        stmt = stmt.order_by(desc(ControlPlaneAlert.created_at)).limit(limit)
        rows = session.execute(stmt).scalars().all()
        return {
            "ok": True,
            "items": [
                {
                    "id": int(r.id),
                    "type": r.type,
                    "message": r.message,
                    "severity": r.severity,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "resolved": bool(r.resolved),
                }
                for r in rows
            ],
        }

