from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select

from api.dependencies import CurrentUser, get_current_user, require_roles
from core.database import get_session_factory
from core.db.models import AuditLog

router = APIRouter(tags=["Audit"])


class AuditCreateBody(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=128)
    entity: str = Field(..., min_length=1, max_length=128)
    entity_id: Optional[str] = Field(None, max_length=128)
    source: Literal["AI", "USER"] = "USER"
    result: Literal["SUCCESS", "FAIL"] = "SUCCESS"
    metadata: Optional[dict[str, Any]] = None


@router.post("/audit")
def create_audit_log(
    body: AuditCreateBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        row = AuditLog(
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            action_type=body.action_type,
            entity=body.entity,
            entity_id=body.entity_id,
            source=body.source,
            result=body.result,
            audit_metadata=body.metadata or {},
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "id": int(row.id)}


@router.get("/audit")
def list_audit_logs(
    q: str | None = None,
    action_type: str | None = None,
    user_id: int | None = None,
    source: str | None = None,
    result: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 100,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "admin", "staff")),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")

    limit = max(1, min(500, int(limit)))
    ts_from = datetime.fromisoformat(from_ts) if from_ts else None
    ts_to = datetime.fromisoformat(to_ts) if to_ts else None

    with factory() as session:
        conds = [AuditLog.organization_id == _user.organization_id]
        if action_type:
            conds.append(AuditLog.action_type == action_type)
        if user_id is not None:
            conds.append(AuditLog.user_id == int(user_id))
        if source:
            conds.append(AuditLog.source == source)
        if result:
            conds.append(AuditLog.result == result)
        if ts_from is not None:
            conds.append(AuditLog.created_at >= ts_from)
        if ts_to is not None:
            conds.append(AuditLog.created_at <= ts_to)
        if q:
            qq = f"%{q.strip()}%"
            conds.append(
                or_(
                    AuditLog.action_type.ilike(qq),
                    AuditLog.entity.ilike(qq),
                    AuditLog.entity_id.ilike(qq),
                )
            )

        stmt = select(AuditLog).where(and_(*conds)).order_by(desc(AuditLog.created_at)).limit(limit)
        rows = session.execute(stmt).scalars().all()

        return {
            "ok": True,
            "items": [
                {
                    "id": int(r.id),
                    "user_id": int(r.user_id) if r.user_id is not None else None,
                    "org_id": int(r.organization_id),
                    "action_type": r.action_type,
                    "entity": r.entity,
                    "entity_id": r.entity_id,
                    "source": r.source,
                    "result": r.result,
                    "metadata": r.audit_metadata or {},
                    "timestamp": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }

