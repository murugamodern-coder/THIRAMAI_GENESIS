"""
Personal Command Center — morning brief, personal finance, vitals, medicine, doctor visits, research, budgets.

Uses ``X-Personal-Vault-Passphrase`` (optional) with ``life_os_service.unlock_fernet`` for encrypted note fields.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import CurrentUser, get_current_user
from services.product_plans import organization_plan_sync, plan_allows
from core.database import get_session_factory
from core.db.models import PersonalMeeting, PersonalMission
from services import life_os_service
from services import personal_command_center_service as pcc
from services.personal_meeting_intelligence import (
    build_meeting_ics,
    find_overlapping_meeting_ids,
    follow_up_mission_title,
    suggest_duration_and_agenda,
)
from services.personal_meetings_service import (
    ARRANGED_BY,
    LOCATION_TYPES,
    MEETING_STATUSES,
    MEETING_TYPES,
    PRIORITIES,
    create_meeting,
    get_meeting_or_none,
    list_meetings,
    list_today,
    list_upcoming,
    serialize_meeting,
    update_meeting_fields,
)

router = APIRouter(prefix="/personal/os", tags=["Personal Command Center"])
_LOG = logging.getLogger(__name__)


def _fernet(user_id: int, passphrase: str | None):
    if not passphrase or not str(passphrase).strip():
        return None
    return life_os_service.unlock_fernet(user_id=user_id, passphrase=passphrase.strip())


@router.get("/morning-brief", summary="Daily command center brief")
async def morning_brief(
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    return pcc.build_morning_brief_sync(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        fernet=fn,
    )


@router.get("/today-brief", summary="Unified Today hero — brief + business + alerts (max 3)")
async def today_brief(
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    from cache.ttl import today_brief_ttl_seconds

    ttl = today_brief_ttl_seconds()
    try:
        if ttl <= 0:
            return await asyncio.to_thread(
                pcc.build_today_brief_sync,
                user_id=int(user.id),
                organization_id=int(user.organization_id),
                fernet=fn,
            )
        from services.cache_layer import cache_key_today_brief, get_or_set_cache

        day = datetime.now(timezone.utc).date().isoformat()
        key = cache_key_today_brief(int(user.id), int(user.organization_id), day) + (":e1" if fn else ":e0")
        uid = int(user.id)
        oid = int(user.organization_id)

        def _compute() -> dict[str, Any]:
            return pcc.build_today_brief_sync(user_id=uid, organization_id=oid, fernet=fn)

        return await asyncio.to_thread(get_or_set_cache, key, ttl, _compute)
    except HTTPException:
        raise
    except Exception as exc:
        _LOG.exception("today_brief_unhandled_error")
        raise HTTPException(status_code=500, detail="Today brief is temporarily unavailable.") from exc


@router.get("/weekly-review", summary="Last 7 days — tasks, spend, health, meetings, suggested priorities")
async def weekly_review(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return pcc.build_weekly_review_sync(user_id=int(user.id), organization_id=int(user.organization_id))


class ExpenseCreateBody(BaseModel):
    amount: Decimal = Field(..., gt=0)
    currency: str = Field("INR", max_length=8)
    category: str = Field(..., max_length=64)
    subcategory: str = Field("", max_length=128)
    spent_at: datetime | None = None
    title: str = Field("", max_length=2000)
    notes: str | None = Field(None, max_length=8000)


@router.get("/expenses", summary="List personal expenses")
async def list_expenses(
    user: CurrentUser = Depends(get_current_user),
    limit: int = 100,
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_expenses_sync(int(user.id), limit=limit)}


@router.post("/expenses", summary="Create personal expense")
async def create_expense(
    body: ExpenseCreateBody,
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    spent = body.spent_at or datetime.now(timezone.utc)
    if spent.tzinfo is None:
        spent = spent.replace(tzinfo=timezone.utc)
    ok, msg, eid = pcc.create_expense_sync(
        user_id=int(user.id),
        amount=body.amount,
        currency=body.currency,
        category=body.category,
        subcategory=body.subcategory,
        spent_at=spent,
        title=body.title,
        notes_plain=body.notes,
        fernet=fn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": eid}


@router.post("/expenses/scan-preview", summary="Upgrade 5: receipt image → structured preview + token")
async def expenses_scan_preview(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    p = organization_plan_sync(int(user.organization_id))
    if not plan_allows(p, "auto_accounting"):
        raise HTTPException(
            status_code=402,
            detail="Receipt AI requires Pro or Business. Upgrade to unlock auto accounting.",
        )
    raw = await file.read()
    from core.security.upload_validation import validate_upload_bytes

    fn = (file.filename or "receipt.jpg").lower()
    ext = fn.rsplit(".", 1)[-1] if "." in fn else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "pdf"):
        ext = "jpg"
    vchk = validate_upload_bytes(
        raw,
        filename=file.filename or f"receipt.{ext}",
        content_type=file.content_type,
        allowed_ext=("jpg", "jpeg", "png", "webp", "pdf"),
    )
    if not vchk.get("ok"):
        raise HTTPException(status_code=400, detail=vchk.get("error") or "invalid upload")
    ct = (file.content_type or "image/jpeg").split(";")[0].strip()
    from services.auto_accounting_service import create_receipt_preview_sync

    return create_receipt_preview_sync(raw, content_type=ct)


class ExpenseScanConfirmBody(BaseModel):
    preview_token: str = Field(..., min_length=8, max_length=200)
    amount: Decimal | None = None
    category: str | None = Field(None, max_length=64)
    title: str | None = Field(None, max_length=2000)
    vendor_name: str | None = Field(None, max_length=500)
    spent_at: datetime | None = None


@router.post("/expenses/scan-confirm", summary="Upgrade 5: confirm preview → personal expense (source=auto_scan)")
async def expenses_scan_confirm(
    body: ExpenseScanConfirmBody,
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    from services.auto_accounting_service import confirm_receipt_expense_sync

    ok, msg, eid = confirm_receipt_expense_sync(
        user_id=int(user.id),
        preview_token=body.preview_token.strip(),
        amount=body.amount,
        category=body.category,
        title=body.title,
        vendor_name=body.vendor_name,
        spent_at=body.spent_at,
        fernet=fn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": eid}


class LoanCreateBody(BaseModel):
    display_name: str = Field(..., max_length=2000)
    loan_kind: str = Field(..., max_length=32)
    lender: str | None = Field(None, max_length=2000)
    principal_outstanding: Decimal | None = None
    emi_amount: Decimal | None = None
    next_due_date: date | None = None
    notes: str | None = None


@router.get("/loans", summary="List personal loans")
async def list_loans(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_loans_sync(int(user.id))}


@router.post("/loans", summary="Create personal loan / EMI tracker row")
async def create_loan(
    body: LoanCreateBody,
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    ok, msg, lid = pcc.create_loan_sync(
        user_id=int(user.id),
        display_name=body.display_name,
        loan_kind=body.loan_kind,
        lender=body.lender,
        principal_outstanding=body.principal_outstanding,
        emi_amount=body.emi_amount,
        next_due_date=body.next_due_date,
        notes_plain=body.notes,
        fernet=fn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": lid}


class VitalCreateBody(BaseModel):
    recorded_at: datetime | None = None
    weight_kg: Decimal | None = None
    bp_systolic: int | None = Field(None, ge=40, le=280)
    bp_diastolic: int | None = Field(None, ge=30, le=200)
    blood_glucose_mg_dl: Decimal | None = None
    sleep_hours: Decimal | None = None
    stress_1_10: int | None = Field(None, ge=1, le=10)
    water_glasses: int | None = Field(None, ge=0, le=100)
    notes: str | None = None


@router.get("/vitals", summary="List vital records")
async def list_vitals(user: CurrentUser = Depends(get_current_user), limit: int = 60) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_vitals_sync(int(user.id), limit=limit)}


@router.post("/vitals", summary="Log vitals")
async def create_vital(
    body: VitalCreateBody,
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    rec = body.recorded_at or datetime.now(timezone.utc)
    if rec.tzinfo is None:
        rec = rec.replace(tzinfo=timezone.utc)
    ok, msg, vid = pcc.create_vital_sync(
        user_id=int(user.id),
        recorded_at=rec,
        weight_kg=body.weight_kg,
        bp_systolic=body.bp_systolic,
        bp_diastolic=body.bp_diastolic,
        blood_glucose_mg_dl=body.blood_glucose_mg_dl,
        sleep_hours=body.sleep_hours,
        stress_1_10=body.stress_1_10,
        water_glasses=body.water_glasses,
        notes_plain=body.notes,
        fernet=fn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": vid}


class MedicineCreateBody(BaseModel):
    name: str = Field(..., max_length=500)
    dosage_text: str = Field("", max_length=2000)
    schedule_json: dict[str, Any] = Field(default_factory=dict)
    started_on: date
    ended_on: date | None = None
    notes: str | None = None


@router.get("/medicines", summary="List medicine trackers")
async def list_medicines(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_medicines_sync(int(user.id))}


@router.post("/medicines", summary="Add medicine tracker")
async def create_medicine(
    body: MedicineCreateBody,
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    ok, msg, mid = pcc.create_medicine_sync(
        user_id=int(user.id),
        name=body.name,
        dosage_text=body.dosage_text,
        schedule_json=body.schedule_json,
        started_on=body.started_on,
        ended_on=body.ended_on,
        notes_plain=body.notes,
        fernet=fn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": mid}


class DoctorVisitBody(BaseModel):
    visited_on: date
    doctor_name: str = Field(..., max_length=500)
    specialty: str | None = None
    location: str | None = None
    diagnosis: str | None = None
    prescription: str | None = None
    follow_up_date: date | None = None


@router.get("/doctor-visits", summary="List doctor visits")
async def list_doctor_visits(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_doctor_visits_sync(int(user.id))}


@router.post("/doctor-visits", summary="Log doctor visit")
async def create_doctor_visit(
    body: DoctorVisitBody,
    user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(default=None, alias="X-Personal-Vault-Passphrase"),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    if (body.diagnosis or body.prescription) and not (x_personal_vault_passphrase or "").strip():
        raise HTTPException(
            status_code=400,
            detail="X-Personal-Vault-Passphrase required when storing diagnosis or prescription.",
        )
    fn = _fernet(int(user.id), x_personal_vault_passphrase)
    ok, msg, did = pcc.create_doctor_visit_sync(
        user_id=int(user.id),
        visited_on=body.visited_on,
        doctor_name=body.doctor_name,
        specialty=body.specialty,
        location=body.location,
        diagnosis_plain=body.diagnosis,
        prescription_plain=body.prescription,
        follow_up_date=body.follow_up_date,
        fernet=fn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": did}


class BudgetCreateBody(BaseModel):
    period_start: date
    period_end: date
    category: str = Field(..., max_length=64)
    subcategory: str = Field("", max_length=128)
    budget_amount: Decimal = Field(..., gt=0)
    currency: str = Field("INR", max_length=8)
    overspend_alert_pct: int = Field(15, ge=0, le=100)


@router.get("/budgets", summary="List personal budgets")
async def list_budgets(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_budgets_sync(int(user.id))}


@router.post("/budgets", summary="Create budget envelope")
async def create_budget(body: BudgetCreateBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    ok, msg, bid = pcc.create_budget_sync(
        user_id=int(user.id),
        period_start=body.period_start,
        period_end=body.period_end,
        category=body.category,
        subcategory=body.subcategory,
        budget_amount=body.budget_amount,
        currency=body.currency,
        overspend_alert_pct=body.overspend_alert_pct,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": bid}


class ResearchCreateBody(BaseModel):
    title: str = Field(..., max_length=2000)
    description: str | None = Field(None, max_length=8000)
    links_json: dict[str, Any] = Field(default_factory=dict)


@router.get("/research", summary="List research projects")
async def list_research(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    return {"items": pcc.list_research_projects_sync(int(user.id))}


@router.post("/research", summary="Create research project shell")
async def create_research(body: ResearchCreateBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    ok, msg, rid = pcc.create_research_project_sync(
        user_id=int(user.id),
        title=body.title,
        description=body.description,
        links_json=body.links_json,
        organization_id=int(user.organization_id),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "id": rid}


# --- Personal meetings / appointments ---


class AttendeeItem(BaseModel):
    name: str = Field("", max_length=200)
    phone: str = Field("", max_length=64)
    email: str = Field("", max_length=320)
    role: str = Field("", max_length=120)


class MeetingCreateBody(BaseModel):
    title: str = Field(..., max_length=4000)
    meeting_type: str = Field(..., max_length=32)
    location_type: str = Field(..., max_length=32)
    location_name: str = Field("", max_length=2000)
    location_address: str | None = Field(None, max_length=8000)
    location_maps_url: str | None = Field(None, max_length=8000)
    scheduled_at: datetime
    duration_minutes: int = Field(60, ge=5, le=24 * 60)
    priority: str = Field("normal", max_length=16)
    agenda: str | None = Field(None, max_length=16000)
    arranged_by: str = Field("self", max_length=16)
    organizer_name: str | None = Field(None, max_length=2000)
    organizer_phone: str | None = Field(None, max_length=64)
    organizer_email: str | None = Field(None, max_length=320)
    attendees_json: list[AttendeeItem] = Field(default_factory=list)
    reminder_minutes: int = Field(30, ge=0, le=24 * 60)
    is_recurring: bool = False
    recurrence_rule: str | None = Field(None, max_length=256)


class MeetingUpdateBody(BaseModel):
    title: str | None = Field(None, max_length=4000)
    meeting_type: str | None = Field(None, max_length=32)
    location_type: str | None = Field(None, max_length=32)
    location_name: str | None = Field(None, max_length=2000)
    location_address: str | None = None
    location_maps_url: str | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=5, le=24 * 60)
    status: str | None = Field(None, max_length=20)
    priority: str | None = Field(None, max_length=16)
    agenda: str | None = None
    notes: str | None = None
    outcome: str | None = None
    arranged_by: str | None = Field(None, max_length=16)
    organizer_name: str | None = None
    organizer_phone: str | None = None
    organizer_email: str | None = None
    attendees_json: list[AttendeeItem] | None = None
    reminder_minutes: int | None = Field(None, ge=0, le=24 * 60)
    is_recurring: bool | None = None
    recurrence_rule: str | None = Field(None, max_length=256)


class MeetingCompleteBody(BaseModel):
    outcome: str | None = Field(None, max_length=16000)


def _require_db():
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return factory


def _validate_meeting_type(v: str) -> None:
    if v not in MEETING_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid meeting_type: {v!r}")


def _validate_location_type(v: str) -> None:
    if v not in LOCATION_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid location_type: {v!r}")


def _validate_priority(v: str) -> None:
    if v not in PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {v!r}")


def _validate_arranged_by(v: str) -> None:
    if v not in ARRANGED_BY:
        raise HTTPException(status_code=400, detail=f"Invalid arranged_by: {v!r}")


def _validate_status(v: str) -> None:
    if v not in MEETING_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {v!r}")


@router.get("/meetings/today", summary="Today's scheduled meetings")
async def meetings_today(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    factory = _require_db()
    now = datetime.now(timezone.utc)
    with factory() as session:
        items = list_today(session, user_id=int(user.id), organization_id=int(user.organization_id), now=now)
    return {"items": items}


@router.get("/meetings/upcoming", summary="Meetings in the next 7 days (active)")
async def meetings_upcoming(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    factory = _require_db()
    now = datetime.now(timezone.utc)
    with factory() as session:
        items = list_upcoming(session, user_id=int(user.id), organization_id=int(user.organization_id), now=now)
    return {"items": items}


@router.get("/meetings/suggestions", summary="Heuristic duration + agenda template (no LLM)")
async def meetings_suggestions(
    meeting_type: str = "other",
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    _validate_meeting_type(meeting_type.strip())
    return suggest_duration_and_agenda(meeting_type.strip())


@router.get("/meetings", summary="List meetings with optional filters")
async def meetings_list(
    user: CurrentUser = Depends(get_current_user),
    date_from: date | None = None,
    date_to: date | None = None,
    meeting_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    if meeting_type:
        _validate_meeting_type(meeting_type.strip())
    if status:
        _validate_status(status.strip())
    factory = _require_db()
    with factory() as session:
        items = list_meetings(
            session,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            date_from=date_from,
            date_to=date_to,
            meeting_type=meeting_type.strip() if meeting_type else None,
            status=status.strip() if status else None,
            limit=limit,
        )
    return {"items": items}


@router.post("/meetings", summary="Create meeting / appointment")
async def meetings_create(body: MeetingCreateBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    _validate_meeting_type(body.meeting_type.strip())
    _validate_location_type(body.location_type.strip())
    _validate_priority(body.priority.strip())
    _validate_arranged_by(body.arranged_by.strip())
    if body.arranged_by.strip() == "other" and not (body.organizer_name or "").strip():
        raise HTTPException(status_code=400, detail="organizer_name required when arranged_by is other")
    factory = _require_db()
    attendees = [a.model_dump() for a in body.attendees_json]
    suggestions = suggest_duration_and_agenda(body.meeting_type.strip())
    with factory() as session:
        with session.begin():
            row = create_meeting(
                session,
                user_id=int(user.id),
                organization_id=int(user.organization_id),
                title=body.title,
                meeting_type=body.meeting_type.strip(),
                location_type=body.location_type.strip(),
                location_name=body.location_name,
                location_address=body.location_address,
                location_maps_url=body.location_maps_url,
                scheduled_at=body.scheduled_at,
                duration_minutes=body.duration_minutes,
                priority=body.priority.strip(),
                agenda=body.agenda,
                arranged_by=body.arranged_by.strip(),
                organizer_name=body.organizer_name,
                organizer_phone=body.organizer_phone,
                organizer_email=body.organizer_email,
                attendees_json=attendees,
                reminder_minutes=body.reminder_minutes,
                is_recurring=body.is_recurring,
                recurrence_rule=body.recurrence_rule,
            )
            cids = find_overlapping_meeting_ids(
                session,
                user_id=int(user.id),
                organization_id=int(user.organization_id),
                scheduled_at=row.scheduled_at,
                duration_minutes=int(row.duration_minutes or 60),
                exclude_meeting_id=int(row.id),
            )
            out = serialize_meeting(row)
    result = {
        "status": "ok",
        "meeting": out,
        "conflict": bool(cids),
        "conflicts_with": cids,
        "suggestions": suggestions,
    }
    try:
        from services.google_calendar_integration_service import try_push_new_meeting

        try_push_new_meeting(
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=int(out["id"]),
        )
    except Exception:
        pass
    try:
        from services.jarvis_agent_event_engine import record_meeting_created_event_sync

        record_meeting_created_event_sync(
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=int(out["id"]),
            title=str(out.get("title") or body.title),
        )
    except Exception:
        pass
    return result


@router.get("/meetings/{meeting_id}/ics", summary="Download iCalendar (.ics) for one meeting")
async def meetings_ics(meeting_id: int, user: CurrentUser = Depends(get_current_user)) -> Response:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    factory = _require_db()
    with factory() as session:
        m = get_meeting_or_none(
            session,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=meeting_id,
        )
        if m is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        ics = build_meeting_ics(m)
    return Response(
        content=ics.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="meeting-{meeting_id}.ics"'},
    )


@router.get("/meetings/{meeting_id}", summary="Get one meeting")
async def meetings_get(meeting_id: int, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    factory = _require_db()
    with factory() as session:
        m = get_meeting_or_none(
            session,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=meeting_id,
        )
        if m is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        out = serialize_meeting(m)
    return {"meeting": out}


@router.put("/meetings/{meeting_id}", summary="Update meeting")
async def meetings_update(
    meeting_id: int,
    body: MeetingUpdateBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    data = body.model_dump(exclude_unset=True)
    if "meeting_type" in data and data["meeting_type"]:
        _validate_meeting_type(str(data["meeting_type"]).strip())
    if "location_type" in data and data["location_type"]:
        _validate_location_type(str(data["location_type"]).strip())
    if "priority" in data and data["priority"]:
        _validate_priority(str(data["priority"]).strip())
    if "arranged_by" in data and data["arranged_by"]:
        _validate_arranged_by(str(data["arranged_by"]).strip())
    if "status" in data and data["status"]:
        _validate_status(str(data["status"]).strip())
    if "attendees_json" in data and data["attendees_json"] is not None:
        norm: list[dict[str, Any]] = []
        for x in data["attendees_json"]:
            if isinstance(x, dict):
                norm.append(AttendeeItem(**{k: x.get(k, "") for k in ("name", "phone", "email", "role")}).model_dump())
        data["attendees_json"] = norm
    allowed = {
        "title",
        "meeting_type",
        "location_type",
        "location_name",
        "location_address",
        "location_maps_url",
        "scheduled_at",
        "duration_minutes",
        "status",
        "priority",
        "agenda",
        "notes",
        "outcome",
        "arranged_by",
        "organizer_name",
        "organizer_phone",
        "organizer_email",
        "attendees_json",
        "reminder_minutes",
        "is_recurring",
        "recurrence_rule",
    }
    kw = {k: v for k, v in data.items() if k in allowed}
    if not kw:
        raise HTTPException(status_code=400, detail="No fields to update.")
    factory = _require_db()
    with factory() as session:
        m = get_meeting_or_none(
            session,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=meeting_id,
        )
        if m is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        with session.begin():
            update_meeting_fields(m, **kw)
            cids = find_overlapping_meeting_ids(
                session,
                user_id=int(user.id),
                organization_id=int(user.organization_id),
                scheduled_at=m.scheduled_at,
                duration_minutes=int(m.duration_minutes or 60),
                exclude_meeting_id=int(meeting_id),
            )
            out = serialize_meeting(m)
    sug = suggest_duration_and_agenda(str(out.get("meeting_type") or "other"))
    try:
        from services.google_calendar_integration_service import push_meeting_event
        from services.personal_meetings_service import ACTIVE_STATUSES

        with factory() as session:
            m2 = get_meeting_or_none(
                session,
                user_id=int(user.id),
                organization_id=int(user.organization_id),
                meeting_id=meeting_id,
            )
            if m2 is not None and m2.status in ACTIVE_STATUSES:
                push_meeting_event(user_id=int(user.id), meeting=m2)
    except Exception:
        pass
    return {
        "status": "ok",
        "meeting": out,
        "conflict": bool(cids),
        "conflicts_with": cids,
        "suggestions": sug,
    }


@router.delete("/meetings/{meeting_id}", summary="Cancel meeting (soft delete)")
async def meetings_delete(meeting_id: int, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    factory = _require_db()
    with factory() as session:
        m = get_meeting_or_none(
            session,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=meeting_id,
        )
        if m is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        google_ev = getattr(m, "google_event_id", None)
        google_ev_s = str(google_ev).strip() if google_ev else ""
        with session.begin():
            m.status = "cancelled"
            out = serialize_meeting(m)
    if google_ev_s:
        try:
            from services.google_calendar_integration_service import delete_calendar_event

            delete_calendar_event(user_id=int(user.id), event_id=google_ev_s)
            with factory() as session:
                with session.begin():
                    m2 = session.get(PersonalMeeting, meeting_id)
                    if m2 is not None and getattr(m2, "google_event_id", None):
                        m2.google_event_id = None
            out = {**out, "google_event_id": None}
        except Exception:
            pass
    return {"status": "ok", "meeting": out}


@router.post("/meetings/{meeting_id}/complete", summary="Mark meeting completed")
async def meetings_complete(
    meeting_id: int,
    body: MeetingCompleteBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    factory = _require_db()
    follow_ref = f"meeting_followup:{int(meeting_id)}"
    mission_id: int | None = None
    title_for_follow = "Follow up: meeting"
    with factory() as session:
        m = get_meeting_or_none(
            session,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            meeting_id=meeting_id,
        )
        if m is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        existing = session.execute(
            select(PersonalMission.id).where(
                PersonalMission.user_id == int(user.id),
                PersonalMission.source_ref == follow_ref,
            )
        ).scalar_one_or_none()
        with session.begin():
            m.status = "completed"
            if body.outcome is not None:
                m.outcome = body.outcome
            title_for_follow = follow_up_mission_title(m)
            out = serialize_meeting(m)
    if existing is None:
        ok, _msg, mid = life_os_service.create_personal_mission(
            user_id=int(user.id),
            title=title_for_follow,
            description="Auto-created when you marked the meeting complete.",
            deadline=None,
            status="open",
            source_ref=follow_ref,
        )
        if ok and mid:
            mission_id = int(mid)
    return {"status": "ok", "meeting": out, "follow_up_mission_id": mission_id}


@router.get("/brain-health", summary="Self-Evolution: model accuracy, patterns, evolution score")
async def brain_health(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Read-only self-evolution dashboard payload.

    Returns active ML model stats, recent learning patterns, open self-coder
    proposals, and a coarse 0..100 evolution score derived from those signals.
    """
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    try:
        return await asyncio.to_thread(_compute_brain_health, int(user.organization_id))
    except HTTPException:
        raise
    except Exception as exc:
        _LOG.exception("brain_health_unhandled_error")
        raise HTTPException(status_code=500, detail="Brain health is temporarily unavailable.") from exc


def _compute_brain_health(organization_id: int) -> dict[str, Any]:
    """Synchronous helper executed in a worker thread (DB + filesystem reads)."""
    from sqlalchemy import func as sa_func, select as sa_select

    from core.db.models import EvolutionTrigger, LearningPattern
    from services.ml import outcome_predictor
    from services.ml.model_registry import ModelRegistry

    factory = get_session_factory()

    active = ModelRegistry.get_active(outcome_predictor.MODEL_NAME)
    latest = ModelRegistry.get_latest(outcome_predictor.MODEL_NAME)
    rolling = outcome_predictor.get_recent_accuracy(days=7)

    pattern_total = 0
    open_proposals = 0
    avg_confidence = 0.0
    if factory is not None:
        with factory() as session:
            pattern_total = int(
                session.execute(
                    sa_select(sa_func.count(LearningPattern.id))
                ).scalar_one()
                or 0
            )
            avg_conf_raw = session.execute(
                sa_select(sa_func.coalesce(sa_func.avg(LearningPattern.confidence), 0.0))
            ).scalar_one()
            try:
                avg_confidence = float(avg_conf_raw or 0.0)
            except (TypeError, ValueError):
                avg_confidence = 0.0
            open_proposals = int(
                session.execute(
                    sa_select(sa_func.count(EvolutionTrigger.id)).where(
                        EvolutionTrigger.status == "proposed"
                    )
                ).scalar_one()
                or 0
            )

    rolling_acc = float(rolling.get("accuracy") or 0.0) if rolling.get("ok") else 0.0
    rolling_samples = int(rolling.get("samples") or 0) if rolling.get("ok") else 0

    learning_rate = "stable"
    if rolling_acc and active and rolling_acc > float(active.accuracy or 0.0) + 0.02:
        learning_rate = "improving"
    elif rolling_acc and active and rolling_acc < float(active.accuracy or 0.0) - 0.05:
        learning_rate = "regressing"

    sklearn_ok = outcome_predictor.sklearn_available()
    has_active_model = bool(active)

    score = 10  # Phase 1 floor: scaffolding exists
    if sklearn_ok:
        score += 10
    if has_active_model:
        score += 15
    if rolling_samples >= 25:
        score += 10
    score += int(round(min(max(rolling_acc, 0.0), 1.0) * 25.0))
    if pattern_total >= 10:
        score += 5
    if pattern_total >= 50:
        score += 5
    score += int(round(min(max(avg_confidence, 0.0), 1.0) * 10.0))
    if open_proposals > 0:
        score += 5
    score = max(0, min(int(score), 100))

    rl_status: dict[str, Any] = {"available": False}
    try:
        from services.ml.rl_trading_agent import get_status as _rl_status

        rl_status = _rl_status()
    except Exception:
        rl_status = {"available": False, "error": "rl_module_unavailable"}

    llm_status: dict[str, Any] = {}
    try:
        from services.llm.local_llama import get_status as _llm_status

        llm_status = _llm_status()
    except Exception:
        llm_status = {"error": "llm_router_unavailable"}

    architect_status: dict[str, Any] = {}
    try:
        from services.architect.architecture_proposer import get_status as _arch_status

        architect_status = _arch_status()
    except Exception:
        architect_status = {"error": "architect_unavailable"}

    world_model_status: dict[str, Any] = {}
    try:
        from services.world_model.bayesian_world_model import get_status as _wm_status

        world_model_status = _wm_status()
    except Exception:
        world_model_status = {"error": "world_model_unavailable"}

    meta_learner_status: dict[str, Any] = {}
    try:
        from services.ml.meta_learner import get_status as _ml_status

        meta_learner_status = _ml_status()
    except Exception:
        meta_learner_status = {"error": "meta_learner_unavailable"}

    # Phase 4 lifts the evolution score ceiling once architect / world-model /
    # meta-learner are reporting non-trivial activity.
    if architect_status.get("counts", {}).get("deployed", 0) > 0:
        score = min(100, score + 5)
    if int(world_model_status.get("snapshot_count") or 0) > 0:
        score = min(100, score + 5)
    if int(meta_learner_status.get("meta_score") or 0) > 0:
        score = min(100, score + int(meta_learner_status.get("meta_score") or 0) // 20)

    schedule_coverage = _self_evolution_schedule_coverage()
    # Reward each wired-and-enabled cron up to +15.
    score = min(100, score + int(schedule_coverage.get("scheduled_score") or 0))

    quant_trading_block: dict[str, Any] = {}
    try:
        quant_trading_block = _compute_quant_trading_block()
        # Phase 5 reward — full quant_trading block contributes up to +10 to the master score.
        score = min(100, score + int(quant_trading_block.get("trading_score", 0) // 10))
    except Exception:
        _LOG.debug("quant_trading_block_unavailable", exc_info=True)
        quant_trading_block = {}

    score = max(0, min(int(score), 100))

    return {
        "ok": True,
        "models": {
            "outcome_predictor": {
                "accuracy": round(float(active.accuracy), 4) if active else 0.0,
                "training_samples": int(active.training_samples) if active else 0,
                "last_trained": active.trained_at.isoformat() if active and active.trained_at else None,
                "version": str(active.version) if active else None,
                "is_active": bool(active),
                "rolling_accuracy_7d": round(rolling_acc, 4),
                "rolling_samples_7d": rolling_samples,
                "latest_version": str(latest.version) if latest else None,
                "sklearn_available": sklearn_ok,
            }
        },
        "learning_rate": learning_rate,
        "patterns_discovered": int(pattern_total),
        "average_pattern_confidence": round(float(avg_confidence), 4),
        "self_coder_proposals": int(open_proposals),
        "evolution_score": int(score),
        "organization_id": int(organization_id),
        "phase": "self_evolution_phase_4",
        "rl_trading": rl_status,
        "llm_router": llm_status,
        "architect": architect_status,
        "world_model_v2": world_model_status,
        "meta_learner": meta_learner_status,
        "schedule": schedule_coverage,
        "quant_trading": quant_trading_block,
    }


def _self_evolution_schedule_coverage() -> dict[str, Any]:
    """Snapshot of which Self-Evolution cron jobs are wired + enabled.

    Returns a dict with per-cron ``wired`` and ``enabled`` booleans plus an
    integer ``scheduled_score`` (0..15) used to bump the evolution score.
    The check is static (env-var + import-presence) so it never touches
    the running scheduler from a request thread.
    """
    import os as _os

    from services import scheduler as _scheduler_module

    crons = {
        "learning_pipeline_nightly": ("learning_pipeline_nightly_cron", "THIRAMAI_LEARNING_NIGHTLY_CRON"),
        "self_evolution_trigger": ("self_evolution_trigger_cron", "THIRAMAI_SELF_EVOLUTION_TRIGGER_CRON"),
        "online_learner_resolve": ("online_learner_resolve_cron", "THIRAMAI_ONLINE_LEARNER_CRON"),
        "causal_graph_populate": ("causal_graph_populate_cron", "THIRAMAI_CAUSAL_GRAPH_CRON"),
        "feature_archive_daily": ("feature_archive_daily_cron", "THIRAMAI_FEATURE_ARCHIVE_CRON"),
        "model_ensemble_train": ("model_ensemble_train_cron", "THIRAMAI_ENSEMBLE_TRAIN_CRON"),
        "architect_auto_propose": ("architect_auto_propose_cron", "THIRAMAI_ARCHITECT_CRON"),
        "world_model_snapshot": ("world_model_snapshot_cron", "THIRAMAI_WORLD_MODEL_CRON"),
        "meta_learning_cycle": ("meta_learning_cycle_cron", "THIRAMAI_META_LEARNER_CRON"),
        "nightly_research": ("nightly_research_cron", "THIRAMAI_NIGHTLY_RESEARCH_CRON"),
    }
    out: dict[str, Any] = {}
    enabled_count = 0
    for label, (attr, env_key) in crons.items():
        wired = hasattr(_scheduler_module.ThiramaiScheduler, attr)
        env_val = (_os.getenv(env_key) or "1").strip().lower()
        enabled = env_val not in ("0", "false", "off", "no")
        out[label] = {"wired": bool(wired), "enabled": bool(enabled and wired), "env_key": env_key}
        if wired and enabled:
            enabled_count += 1
    out["scheduled_score"] = min(15, int(round((enabled_count / max(1, len(crons))) * 15)))
    out["wired_count"] = sum(1 for c in out.values() if isinstance(c, dict) and c.get("wired"))
    out["enabled_count"] = enabled_count
    out["total"] = len(crons)
    return out


@router.get("/quant-status", summary="Self-Evolution 90/100: quant + tick stream + HAL status")
async def quant_status(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Snapshot for the Self-Evolution 90/100 milestone.

    Reports on the OHLCV store, backtester registry, Kite tick stream worker,
    and HAL device registry; rolls them up into a coarse 0..100 ``quant_score``.
    """
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    try:
        return await asyncio.to_thread(_compute_quant_status)
    except Exception as exc:
        _LOG.exception("quant_status_unhandled_error")
        raise HTTPException(status_code=500, detail="Quant status is temporarily unavailable.") from exc


def _compute_quant_status() -> dict[str, Any]:
    ohlcv_summary: dict[str, Any] = {"tables_exist": False, "symbol_count": 0, "total_candles": 0}
    try:
        from services.quant.ohlcv_store import store_summary

        ohlcv_summary = store_summary()
    except Exception as exc:
        _LOG.debug("ohlcv_summary_unavailable: %s", exc)

    backtester_info: dict[str, Any] = {"available": False, "strategies_registered": 0}
    try:
        from services.quant.backtester import RSIMACDStrategy  # noqa: F401
        from services.quant.strategy_registry import StrategyRegistry

        backtester_info = {
            "available": True,
            "strategies_registered": len(StrategyRegistry.list_active()),
        }
    except Exception as exc:
        _LOG.debug("backtester_unavailable: %s", exc)

    tick_info: dict[str, Any] = {"is_running": False, "kite_enabled": False}
    try:
        from workers.market_tick_stream import get_tick_stream

        tick_info = get_tick_stream().status()
    except Exception as exc:
        _LOG.debug("tick_stream_unavailable: %s", exc)

    hal_info: dict[str, Any] = {"registered": 0, "connected": 0, "mqtt_enabled": False}
    try:
        import os as _os

        from services.hal.hal_base import DeviceRegistry

        hal_info = {
            "registered": DeviceRegistry.total(),
            "connected": DeviceRegistry.connected_count(),
            "mqtt_enabled": bool((_os.getenv("MQTT_BROKER_HOST") or "").strip()),
        }
    except Exception as exc:
        _LOG.debug("hal_unavailable: %s", exc)

    score = 0
    if ohlcv_summary.get("tables_exist"):
        score += 25
        if int(ohlcv_summary.get("total_candles") or 0) > 0:
            score += 10
    if backtester_info.get("available"):
        score += 20
        if int(backtester_info.get("strategies_registered") or 0) > 0:
            score += 5
    if tick_info.get("kite_enabled"):
        score += 10
        if tick_info.get("is_running"):
            score += 10
    if int(hal_info.get("registered") or 0) > 0:
        score += 10
        if int(hal_info.get("connected") or 0) > 0:
            score += 10
    score = max(0, min(int(score), 100))

    return {
        "ok": True,
        "ohlcv_store": ohlcv_summary,
        "backtester": backtester_info,
        "tick_stream": tick_info,
        "hal_devices": hal_info,
        "quant_score": int(score),
        "phase": "self_evolution_phase_5",
    }


@router.get("/paper-trading", summary="Self-Evolution 95/100: paper trading positions + P&L summary")
async def paper_trading_status(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Open paper positions (mark-to-market) plus a closed-trade PnL summary."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _read() -> dict[str, Any]:
        try:
            from services.quant.paper_trader import PaperTrader

            pt = PaperTrader(org_id=int(user.organization_id))
            return {
                "ok": True,
                "open_positions": pt.get_open_positions(),
                "summary": pt.get_paper_pnl_summary(),
                "paper_mode": True,
            }
        except Exception as exc:
            _LOG.exception("paper_trading_status_failed")
            return {"ok": False, "error": str(exc)}

    return await asyncio.to_thread(_read)


@router.post("/paper-trading/run", summary="Self-Evolution 95/100: trigger one paper-trading cycle")
async def paper_trading_run(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run one auto-strategy cycle and place paper orders during NSE hours."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        try:
            from services.quant.paper_trader import PaperTrader

            pt = PaperTrader(org_id=int(user.organization_id))
            return pt.auto_run_strategy()
        except Exception as exc:
            _LOG.exception("paper_trading_run_failed")
            return {"ok": False, "error": str(exc)}

    return await asyncio.to_thread(_run)


@router.get("/backtest-results", summary="Self-Evolution 95/100: recent strategy_runs from DB")
async def backtest_results(
    limit: int = 25,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List recent backtest runs ordered by created_at DESC (max 100 rows)."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    capped = max(1, min(int(limit), 100))

    def _read() -> dict[str, Any]:
        from sqlalchemy import text as _text

        from core.database import get_engine as _get_engine

        engine = _get_engine()
        if engine is None:
            return {"ok": False, "error": "database_unavailable", "results": []}
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    _text(
                        """
                        SELECT strategy_name, symbol, run_type,
                               total_trades, win_rate, total_pnl,
                               sharpe_ratio, max_drawdown, created_at
                        FROM strategy_runs
                        ORDER BY created_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": int(capped)},
                ).fetchall()
        except Exception as exc:
            _LOG.exception("backtest_results_failed")
            return {"ok": False, "error": str(exc), "results": []}

        items = [
            {
                "strategy_name": r[0],
                "symbol": r[1],
                "run_type": r[2],
                "total_trades": int(r[3] or 0),
                "win_rate": float(r[4] or 0),
                "total_pnl": float(r[5] or 0),
                "sharpe_ratio": float(r[6] or 0),
                "max_drawdown": float(r[7] or 0),
                "created_at": str(r[8]) if r[8] else None,
            }
            for r in rows
        ]
        return {"ok": True, "count": len(items), "results": items}

    return await asyncio.to_thread(_read)


def _compute_quant_trading_block() -> dict[str, Any]:
    """Build the ``quant_trading`` payload + 0..100 score used by ``brain-health``.

    Score breakdown:
      * +20 ohlcv_data has 10+ symbols
      * +20 at least one backtest run completed
      * +20 paper trades present (open or closed)
      * +20 closed-trade win rate > 50%
      * +20 best Sharpe ratio across runs > 0.5
    """
    from sqlalchemy import text as _text

    from core.database import get_engine as _get_engine

    out: dict[str, Any] = {
        "ohlcv_symbols": 0,
        "ohlcv_total_candles": 0,
        "backtest_runs": 0,
        "best_sharpe": 0.0,
        "paper_trades": 0,
        "paper_pnl": 0.0,
        "win_rate": 0.0,
        "trading_score": 0,
    }

    engine = _get_engine()
    if engine is None:
        return out

    try:
        with engine.connect() as conn:
            row = conn.execute(
                _text(
                    """
                    SELECT COUNT(DISTINCT symbol), COUNT(*)
                    FROM ohlcv_data
                    """
                )
            ).first()
            if row:
                out["ohlcv_symbols"] = int(row[0] or 0)
                out["ohlcv_total_candles"] = int(row[1] or 0)
    except Exception as exc:
        _LOG.debug("ohlcv_count_failed: %s", exc)

    try:
        with engine.connect() as conn:
            row = conn.execute(
                _text(
                    """
                    SELECT COUNT(*), COALESCE(MAX(sharpe_ratio), 0)
                    FROM strategy_runs
                    """
                )
            ).first()
            if row:
                out["backtest_runs"] = int(row[0] or 0)
                out["best_sharpe"] = float(row[1] or 0)
    except Exception as exc:
        _LOG.debug("strategy_runs_count_failed: %s", exc)

    try:
        with engine.connect() as conn:
            row = conn.execute(
                _text(
                    """
                    SELECT COUNT(*),
                           COALESCE(SUM(realized_pnl), 0),
                           SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END),
                           SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END)
                    FROM paper_trades
                    """
                )
            ).first()
            if row:
                total = int(row[0] or 0)
                closed = int(row[3] or 0)
                wins = int(row[2] or 0)
                out["paper_trades"] = total
                out["paper_pnl"] = float(row[1] or 0)
                out["win_rate"] = (wins / closed) if closed else 0.0
    except Exception as exc:
        _LOG.debug("paper_trades_count_failed: %s", exc)

    score = 0
    if int(out["ohlcv_symbols"]) >= 10:
        score += 20
    if int(out["backtest_runs"]) > 0:
        score += 20
    if int(out["paper_trades"]) > 0:
        score += 20
    if float(out["win_rate"]) > 0.5:
        score += 20
    if float(out["best_sharpe"]) > 0.5:
        score += 20
    out["trading_score"] = int(max(0, min(score, 100)))
    return out
