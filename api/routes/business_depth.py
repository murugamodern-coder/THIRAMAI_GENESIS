"""
Phase 4 Business OS: departments, staff, attendance, operational expenses — tenant-scoped (JWT active org).
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from services import audit_service, business_depth_service
from services.business_snapshot_service import build_business_snapshot
from services.economics_service import get_business_margin

router = APIRouter(prefix="/business", tags=["Business OS"])


def _correlation_id(request: Request) -> str | None:
    h = (request.headers.get("X-Correlation-ID") or "").strip()
    if h:
        return h[:128]
    cid = getattr(request.state, "correlation_id", None)
    return cid if isinstance(cid, str) else None


def _low_stock_threshold() -> int:
    raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
    try:
        return max(0, min(10_000, int(raw)))
    except ValueError:
        return 5


@router.get("/snapshot", summary="Unified Business OS JSON (sales vs target, stock, attendance, monthly profit)")
async def business_snapshot(
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return build_business_snapshot(
        _user.organization_id,
        low_stock_threshold=_low_stock_threshold(),
    )


@router.get("/economics/margin", summary="Current month revenue, COGS, salaries, opex, net profit (management KPI)")
async def business_margin(
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return get_business_margin(_user.organization_id)


class DepartmentLeadBody(BaseModel):
    lead_user_id: int | None = Field(None, description="Set null to clear department lead")


@router.put("/departments/{department_id}/lead", summary="Assign department lead (user id in same org)")
async def set_department_lead(
    request: Request,
    department_id: int,
    body: DepartmentLeadBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    ok, msg = business_depth_service.set_department_lead(
        organization_id=_user.organization_id,
        department_id=department_id,
        lead_user_id=body.lead_user_id,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="department_set_lead",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="department",
        extra={"department_id": department_id, "lead_user_id": body.lead_user_id},
    )
    return {"status": "ok"}


class StaffUpsertBody(BaseModel):
    user_id: int = Field(..., ge=1)
    department_id: int | None = None
    basic_salary: Decimal = Field(default_factory=lambda: Decimal("0"))
    joining_date: date | None = None
    status: str = Field("active", max_length=32)


@router.post("/staff", summary="Create or update staff profile for active organization")
async def staff_upsert(
    request: Request,
    body: StaffUpsertBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    ok, msg, sid = business_depth_service.upsert_staff_profile(
        organization_id=_user.organization_id,
        user_id=body.user_id,
        department_id=body.department_id,
        basic_salary=body.basic_salary,
        joining_date=body.joining_date,
        status=body.status,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="staff_profile_upsert",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="staff_profile",
        extra={"staff_profile_id": sid, "target_user_id": body.user_id},
    )
    return {"status": "ok", "staff_profile_id": sid}


class AttendanceCheckInBody(BaseModel):
    staff_profile_id: int = Field(..., ge=1)
    check_in: datetime | None = None
    status: str = Field("present", max_length=32)


@router.post("/attendance/check-in", summary="Log staff check-in")
async def attendance_check_in(
    request: Request,
    body: AttendanceCheckInBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    ok, msg, lid = business_depth_service.attendance_check_in(
        organization_id=_user.organization_id,
        staff_profile_id=body.staff_profile_id,
        check_in=body.check_in,
        status=body.status,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="attendance_check_in",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="attendance_log",
        extra={"attendance_log_id": lid, "staff_profile_id": body.staff_profile_id},
    )
    return {"status": "ok", "attendance_log_id": lid}


class AttendanceCheckOutBody(BaseModel):
    attendance_log_id: int | None = Field(None, ge=1)
    staff_profile_id: int | None = Field(None, ge=1)
    check_out: datetime | None = None


@router.post("/attendance/check-out", summary="Log check-out (by log id or latest open log for staff)")
async def attendance_check_out(
    request: Request,
    body: AttendanceCheckOutBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    ok, msg = business_depth_service.attendance_check_out(
        organization_id=_user.organization_id,
        attendance_log_id=body.attendance_log_id,
        staff_profile_id=body.staff_profile_id,
        check_out=body.check_out,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="attendance_check_out",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="attendance_log",
        extra={
            "attendance_log_id": body.attendance_log_id,
            "staff_profile_id": body.staff_profile_id,
        },
    )
    return {"status": "ok"}


class OperationalExpenseBody(BaseModel):
    expense_date: date
    category: str = Field(..., min_length=1, max_length=64)
    amount_inr: Decimal = Field(...)
    description: str | None = Field(None, max_length=2000)


@router.post("/expenses", summary="Record operational expense (feeds net profit rollup)")
async def operational_expense_create(
    request: Request,
    body: OperationalExpenseBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    ok, msg, eid = business_depth_service.record_operational_expense(
        organization_id=_user.organization_id,
        expense_date=body.expense_date,
        category=body.category,
        amount_inr=body.amount_inr,
        description=body.description,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="operational_expense_create",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="operational_expense",
        extra={"expense_id": eid, "category": body.category[:64], "amount_inr": str(body.amount_inr)},
    )
    return {"status": "ok", "expense_id": eid}
