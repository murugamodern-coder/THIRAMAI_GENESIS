"""
Life OS — daily planner, health logs, personal reminders, personal vault crypto (JWT user-scoped).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from services import audit_service, life_os_service
from services.stock_market_service import list_equity_move_alerts_for_user_sync

router = APIRouter(prefix="/life", tags=["Life OS"])


def _correlation_id(request: Request) -> str | None:
    """Prefer client ``X-Correlation-ID``; fall back to middleware-populated ``request.state``."""
    h = (request.headers.get("X-Correlation-ID") or "").strip()
    if h:
        return h[:128]
    cid = getattr(request.state, "correlation_id", None)
    return cid if isinstance(cid, str) else None


class VaultInitBody(BaseModel):
    passphrase: str = Field(..., min_length=8, max_length=256)


class PlannerUpsertBody(BaseModel):
    for_date: date | None = None
    blocks: list[Any] = Field(default_factory=list)


class HealthUpsertBody(BaseModel):
    logged_on: date | None = None
    sleep_hours: float | None = None
    water_glasses: int | None = None
    stress_1_10: int | None = Field(None, ge=1, le=10)
    weight_kg: float | None = Field(None, ge=0, le=500)
    bp_systolic: int | None = Field(None, ge=40, le=280)
    bp_diastolic: int | None = Field(None, ge=30, le=200)
    reflection: str | None = Field(None, max_length=8000)


class ReminderCreateBody(BaseModel):
    title: str = Field("", max_length=500)
    remind_at: datetime
    body: str | None = Field(None, max_length=8000)


class HabitCheckInBody(BaseModel):
    habit_id: int = Field(..., ge=1)
    status: str = Field("completed", max_length=32)


class HabitCreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=2000)
    goal_frequency: str = Field("daily", max_length=32)
    category: str | None = Field(None, max_length=32)


class PersonalMissionUpsertBody(BaseModel):
    """Create a mission, or update when ``mission_id`` is the owning user's row."""

    mission_id: int | None = Field(None, ge=1)
    title: str = Field(..., min_length=1, max_length=2000)
    description: str | None = Field(None, max_length=8000)
    deadline: datetime | None = None
    status: str = Field("open", max_length=32)
    progress_percent: int | None = Field(None, ge=0, le=100)
    priority: str | None = Field(None, max_length=8, description="P1, P2, or P3")


@router.get("/dashboard", summary="Today's habits, health metrics, and open missions (syncs vault JSON → Postgres)")
async def life_dashboard(
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    return life_os_service.build_life_dashboard_payload(user_id=_user.id)


@router.post("/habit", summary="Create a personal habit")
async def life_habit_create(
    request: Request,
    body: HabitCreateBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    ok, msg, hid = life_os_service.create_personal_habit(
        user_id=_user.id,
        title=body.title,
        goal_frequency=body.goal_frequency,
        category=body.category,
    )
    if not ok or hid is None:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_life_os_mutation(
        correlation_id=_correlation_id(request),
        action_name="habit_create",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="habit",
        extra={"habit_id": hid, "title": body.title[:200]},
    )
    return {"status": "ok", "habit_id": hid}


@router.post("/habit/check-in", summary="Log habit completion (or skip)")
async def life_habit_check_in(
    request: Request,
    body: HabitCheckInBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    ok, msg = life_os_service.log_habit_check_in(
        user_id=_user.id,
        habit_id=body.habit_id,
        status=body.status,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    if msg == "ok":
        audit_service.log_life_os_mutation(
            correlation_id=_correlation_id(request),
            action_name="habit_check_in",
            user_id=_user.id,
            organization_id=_user.organization_id,
            resource_type="habit_log",
            extra={"habit_id": body.habit_id, "status": body.status},
        )
    return {"status": "ok", "detail": msg}


@router.get("/reminders/hub", summary="Reminders + proactive stock move alerts for dashboard bell")
async def life_reminders_hub(
    limit: int = Query(40, ge=1, le=100),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    lim = int(limit)
    stock_alerts = await asyncio.to_thread(list_equity_move_alerts_for_user_sync, user_id=int(_user.id))
    rem_cap = max(1, lim - len(stock_alerts))
    reminders = await asyncio.to_thread(
        life_os_service.list_hub_reminders_sync,
        user_id=int(_user.id),
        limit=rem_cap,
    )
    items = list(stock_alerts) + list(reminders)
    if len(items) > lim:
        items = items[:lim]
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/mission", summary="Create or update a personal mission / long-term goal")
async def life_mission_upsert(
    request: Request,
    body: PersonalMissionUpsertBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    ok, msg, mid, created = life_os_service.upsert_personal_mission(
        user_id=_user.id,
        mission_id=body.mission_id,
        title=body.title,
        description=body.description,
        deadline=body.deadline,
        status=body.status,
        progress_percent=body.progress_percent,
        priority=body.priority,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_life_os_mutation(
        correlation_id=_correlation_id(request),
        action_name="personal_mission_upsert",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="personal_mission",
        extra={"mission_id": mid, "title": body.title[:200], "created": created},
    )
    return {"status": "ok", "mission_id": mid, "created": created}


@router.post("/vault/init", summary="Initialize personal vault crypto (PBKDF2 + Fernet verifier)")
async def life_vault_init(
    request: Request,
    body: VaultInitBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id (not dev bypass).")
    ok, msg = life_os_service.init_personal_vault(user_id=_user.id, passphrase=body.passphrase)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_life_os_mutation(
        correlation_id=_correlation_id(request),
        action_name="vault_init",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="personal_vault",
    )
    return {"status": "ok"}


@router.put("/planner", summary="Upsert daily planner blocks (JSON) for a date")
async def life_planner_upsert(
    request: Request,
    body: PlannerUpsertBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    d = body.for_date or datetime.now(timezone.utc).date()
    ok = life_os_service.upsert_daily_planner_blocks(user_id=_user.id, for_date=d, blocks=body.blocks)
    if not ok:
        raise HTTPException(status_code=503, detail="database_unavailable")
    audit_service.log_life_os_mutation(
        correlation_id=_correlation_id(request),
        action_name="planner_upsert",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="daily_planner",
        extra={"for_date": d.isoformat(), "block_count": len(body.blocks or [])},
    )
    return {"status": "ok", "for_date": d.isoformat()}


@router.post("/health", summary="Upsert health log; encrypted reflection requires vault passphrase header")
async def life_health_upsert(
    request: Request,
    body: HealthUpsertBody,
    _user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, str]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    d = body.logged_on or datetime.now(timezone.utc).date()
    fernet = None
    if x_personal_vault_passphrase and body.reflection and body.reflection.strip():
        fernet = life_os_service.unlock_fernet(user_id=_user.id, passphrase=x_personal_vault_passphrase)
        if fernet is None:
            raise HTTPException(status_code=401, detail="invalid vault passphrase")
    sh = Decimal(str(body.sleep_hours)) if body.sleep_hours is not None else None
    wk = Decimal(str(body.weight_kg)) if body.weight_kg is not None else None
    ok, msg = life_os_service.upsert_health_metrics(
        user_id=_user.id,
        logged_on=d,
        sleep_hours=sh,
        water_glasses=body.water_glasses,
        stress_1_10=body.stress_1_10,
        weight_kg=wk,
        bp_systolic=body.bp_systolic,
        bp_diastolic=body.bp_diastolic,
        reflection_plain=body.reflection,
        fernet=fernet,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_life_os_mutation(
        correlation_id=_correlation_id(request),
        action_name="health_upsert",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="health_log",
        extra={"logged_on": d.isoformat(), "has_reflection": bool(body.reflection and body.reflection.strip())},
    )
    return {"status": "ok", "logged_on": d.isoformat()}


@router.post("/reminders", summary="Create reminder; encrypted body requires vault passphrase header")
async def life_reminder_create(
    request: Request,
    body: ReminderCreateBody,
    _user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, str]:
    if _user.id <= 0:
        raise HTTPException(status_code=400, detail="Life OS requires a real user id.")
    fernet = None
    if body.body and body.body.strip():
        if not x_personal_vault_passphrase:
            raise HTTPException(
                status_code=400,
                detail="X-Personal-Vault-Passphrase required to store encrypted reminder body.",
            )
        fernet = life_os_service.unlock_fernet(user_id=_user.id, passphrase=x_personal_vault_passphrase)
        if fernet is None:
            raise HTTPException(status_code=401, detail="invalid vault passphrase")
    ok, msg = life_os_service.add_personal_reminder(
        user_id=_user.id,
        remind_at=body.remind_at,
        title=body.title,
        body_plain=body.body,
        fernet=fernet,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_life_os_mutation(
        correlation_id=_correlation_id(request),
        action_name="reminder_create",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="personal_reminder",
        extra={"remind_at": body.remind_at.isoformat(), "encrypted_body": fernet is not None},
    )
    return {"status": "ok"}
