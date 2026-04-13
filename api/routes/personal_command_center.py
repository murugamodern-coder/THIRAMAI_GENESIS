"""
Personal Command Center — morning brief, personal finance, vitals, medicine, doctor visits, research, budgets.

Uses ``X-Personal-Vault-Passphrase`` (optional) with ``life_os_service.unlock_fernet`` for encrypted note fields.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import CurrentUser, get_current_user
from core.database import get_session_factory
from core.db.models import PersonalMission
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
    return pcc.build_today_brief_sync(
        user_id=int(user.id),
        organization_id=int(user.organization_id),
        fernet=fn,
    )


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
