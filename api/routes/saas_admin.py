from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from api.dependencies import CurrentUser, require_roles
from core.database import get_session_factory
from core.db.models import Organization, SaasUsageMetric

router = APIRouter(tags=["SaaS Admin"], prefix="/admin")


class OrgDisableBody(BaseModel):
    is_disabled: bool = Field(..., description="Kill switch for an organization")


@router.get("/organizations")
def list_organizations(
    limit: int = 200,
    _user: CurrentUser = Depends(require_roles("superadmin")),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    limit = max(1, min(1000, int(limit)))
    with factory() as session:
        stmt = select(Organization).order_by(desc(Organization.created_at)).limit(limit)
        rows = session.execute(stmt).scalars().all()
        return {
            "ok": True,
            "items": [
                {
                    "id": int(o.id),
                    "name": o.name,
                    "plan": getattr(o, "plan", "free") or "free",
                    "is_disabled": bool(getattr(o, "is_disabled", False)),
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in rows
            ],
        }


@router.post("/organizations/{org_id}/disable")
def set_org_disabled(
    org_id: int,
    body: OrgDisableBody,
    _user: CurrentUser = Depends(require_roles("superadmin")),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        org = session.get(Organization, int(org_id))
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        org.is_disabled = bool(body.is_disabled)
        session.add(org)
        session.commit()
        return {"ok": True, "id": int(org.id), "is_disabled": bool(org.is_disabled)}


@router.get("/usage")
def usage_summary(
    limit: int = 200,
    _user: CurrentUser = Depends(require_roles("superadmin")),
) -> dict[str, Any]:
    """
    Provider-level usage view. Reads from saas_usage_metrics (aggregated) if populated.
    """
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    limit = max(1, min(1000, int(limit)))
    with factory() as session:
        stmt = select(SaasUsageMetric).order_by(desc(SaasUsageMetric.updated_at)).limit(limit)
        rows = session.execute(stmt).scalars().all()
        return {
            "ok": True,
            "items": [
                {
                    "org_id": int(r.organization_id),
                    "user_id": int(r.user_id) if r.user_id is not None else None,
                    "metric": r.metric,
                    "window_start": r.window_start.isoformat(),
                    "window_end": r.window_end.isoformat(),
                    "value": int(r.value),
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
        }

