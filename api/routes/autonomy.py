from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from api.dependencies import CurrentUser, get_current_user, require_roles
from core.database import get_session_factory
from core.db.models import AiDecision, AuditLog, AutonomySetting

router = APIRouter(tags=["Autonomy"])


class AutonomySettingsResponse(BaseModel):
    auto_mode_enabled: bool
    policy: dict[str, Any] = Field(default_factory=dict)


class AutonomySettingsUpsert(BaseModel):
    auto_mode_enabled: bool = False
    policy: dict[str, Any] = Field(default_factory=dict)


@router.get("/autonomy/settings", response_model=AutonomySettingsResponse)
def get_autonomy_settings(
    _user: CurrentUser = Depends(get_current_user),
) -> AutonomySettingsResponse:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        row = session.scalar(
            select(AutonomySetting).where(AutonomySetting.organization_id == _user.organization_id).limit(1)
        )
        if row is None:
            return AutonomySettingsResponse(auto_mode_enabled=False, policy={})
        return AutonomySettingsResponse(
            auto_mode_enabled=bool(row.auto_mode_enabled),
            policy=dict(row.policy or {}),
        )


@router.put("/autonomy/settings", response_model=AutonomySettingsResponse)
def upsert_autonomy_settings(
    body: AutonomySettingsUpsert,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> AutonomySettingsResponse:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        with session.begin():
            row = session.scalar(
                select(AutonomySetting).where(AutonomySetting.organization_id == _user.organization_id).limit(1)
            )
            if row is None:
                row = AutonomySetting(organization_id=_user.organization_id)
                session.add(row)
            row.auto_mode_enabled = bool(body.auto_mode_enabled)
            row.policy = dict(body.policy or {})
        session.refresh(row)
        return AutonomySettingsResponse(auto_mode_enabled=bool(row.auto_mode_enabled), policy=dict(row.policy or {}))


@router.get("/autonomy/status")
def autonomy_status(
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with factory() as session:
        row = session.scalar(
            select(AutonomySetting).where(AutonomySetting.organization_id == _user.organization_id).limit(1)
        )
        auto_mode_enabled = bool(getattr(row, "auto_mode_enabled", False)) if row is not None else False

        pending = 0
        try:
            pending = int(
                session.scalar(
                    select(func.count()).select_from(AiDecision).where(
                        AiDecision.organization_id == _user.organization_id, AiDecision.status == "pending"
                    )
                )
                or 0
            )
        except Exception:
            pending = 0

        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        executed_last_1h = int(
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.organization_id == _user.organization_id,
                    AuditLog.action_type == "AUTO_ACTION",
                    AuditLog.result == "SUCCESS",
                    AuditLog.created_at >= cutoff,
                )
            )
            or 0
        )
        blocked_last_1h = int(
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.organization_id == _user.organization_id,
                    AuditLog.action_type == "AUTO_ACTION",
                    AuditLog.result == "BLOCKED",
                    AuditLog.created_at >= cutoff,
                )
            )
            or 0
        )
        last_run_at = session.scalar(
            select(func.max(AuditLog.created_at)).where(
                AuditLog.organization_id == _user.organization_id,
                AuditLog.action_type == "AUTO_ACTION",
            )
        )

        return {
            "ok": True,
            "auto_mode_enabled": auto_mode_enabled,
            "pending_decisions": pending,
            "executed_last_1h": executed_last_1h,
            "blocked_last_1h": blocked_last_1h,
            "last_run_at": last_run_at.isoformat() if last_run_at else None,
        }

