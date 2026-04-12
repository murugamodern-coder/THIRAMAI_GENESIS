"""
Personal Command Center — morning brief, personal finance, vitals, medicine, doctor visits, research, budgets.

Uses ``X-Personal-Vault-Passphrase`` (optional) with ``life_os_service.unlock_fernet`` for encrypted note fields.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from services import life_os_service
from services import personal_command_center_service as pcc

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
