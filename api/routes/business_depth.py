"""
Phase 4 Business OS: departments, staff, attendance, operational expenses — tenant-scoped (JWT active org).
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Request, UploadFile
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from services import audit_service, business_depth_service, business_os_service
from services.product_plans import organization_plan_sync, plan_allows
from services.business_snapshot_service import build_business_snapshot
from services.economics_service import get_business_margin

router = APIRouter(prefix="/business", tags=["Business OS"])


def _correlation_id(request: Request) -> str | None:
    h = (request.headers.get("X-Correlation-ID") or "").strip()
    if h:
        return h[:128]
    cid = getattr(request.state, "correlation_id", None)
    return cid if isinstance(cid, str) else None


def _require_auto_accounting(user: CurrentUser) -> None:
    p = organization_plan_sync(int(user.organization_id))
    if not plan_allows(p, "auto_accounting"):
        raise HTTPException(
            status_code=402,
            detail="Auto accounting (receipts, bank import, GST assist) requires Pro or Business.",
        )


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


@router.get("/expenses/list", summary="List operational expenses for active organization")
async def operational_expense_list(
    limit: int = Query(200, ge=1, le=500),
    from_date: str | None = Query(None, description="YYYY-MM-DD inclusive lower bound"),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    fd: date | None = None
    if from_date and from_date.strip():
        try:
            parts = from_date.strip().split("-")
            if len(parts) == 3:
                fd = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date must be YYYY-MM-DD") from None
    out = business_os_service.list_operational_expenses_sync(
        organization_id=_user.organization_id,
        limit=limit,
        from_date=fd,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return out


@router.get("/pl-daily", summary="Today vs MTD sales, opex, and net (bills + dated invoices)")
async def business_pl_daily(_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = business_os_service.daily_pl_summary_sync(organization_id=_user.organization_id)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "pl failed")
    return out


@router.get("/liquidity", summary="Cash + bank balance (manual ledger)")
async def business_liquidity_get(_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    out = business_os_service.get_liquidity_sync(organization_id=_user.organization_id)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "read failed")
    return out


class LiquidityPutBody(BaseModel):
    cash_inr: Decimal = Field(default_factory=lambda: Decimal("0"))
    bank_inr: Decimal = Field(default_factory=lambda: Decimal("0"))


@router.put("/liquidity", summary="Update cash + bank balance for active org")
async def business_liquidity_put(
    body: LiquidityPutBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    out = business_os_service.upsert_liquidity_sync(
        organization_id=_user.organization_id,
        cash_inr=body.cash_inr,
        bank_inr=body.bank_inr,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "update failed")
    return {"status": "ok"}


@router.get("/expenses/monthly-report", summary="Operational expenses aggregated by category for a month")
async def business_expenses_monthly(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    out = business_os_service.monthly_expense_report_sync(
        organization_id=_user.organization_id, year=year, month=month
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "report failed")
    return out


@router.get("/subsidy", summary="List agro subsidy cases")
async def subsidy_list(
    limit: int = Query(200, ge=1, le=500),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    out = business_os_service.list_subsidy_cases_sync(organization_id=_user.organization_id, limit=limit)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return out


class SubsidyCreateBody(BaseModel):
    farmer_name: str = Field(..., min_length=1)
    village: str = ""
    survey_number: str = ""
    farmer_phone: str | None = None
    land_acres: Decimal | None = None
    scheme_name: str = Field(..., min_length=1)
    application_status: str = "draft"
    subsidy_applied_inr: Decimal = Field(default_factory=lambda: Decimal("0"))
    subsidy_approved_inr: Decimal = Field(default_factory=lambda: Decimal("0"))
    subsidy_pending_inr: Decimal = Field(default_factory=lambda: Decimal("0"))
    subsidy_received_inr: Decimal = Field(default_factory=lambda: Decimal("0"))
    commission_earned_inr: Decimal = Field(default_factory=lambda: Decimal("0"))
    follow_up_date: date | None = None
    notes: str | None = None


@router.post("/subsidy", summary="Create agro subsidy case")
async def subsidy_create(
    request: Request,
    body: SubsidyCreateBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    out = business_os_service.create_subsidy_case_sync(
        organization_id=_user.organization_id,
        farmer_name=body.farmer_name,
        village=body.village,
        survey_number=body.survey_number,
        farmer_phone=body.farmer_phone,
        land_acres=body.land_acres,
        scheme_name=body.scheme_name,
        application_status=body.application_status,
        subsidy_applied_inr=body.subsidy_applied_inr,
        subsidy_approved_inr=body.subsidy_approved_inr,
        subsidy_pending_inr=body.subsidy_pending_inr,
        subsidy_received_inr=body.subsidy_received_inr,
        commission_earned_inr=body.commission_earned_inr,
        follow_up_date=body.follow_up_date,
        notes=body.notes,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create failed")
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="agro_subsidy_create",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="agro_subsidy_case",
        extra={"case_id": out.get("id")},
    )
    return {"status": "ok", "id": out.get("id")}


class SubsidyPatchBody(BaseModel):
    farmer_name: str | None = None
    village: str | None = None
    survey_number: str | None = None
    farmer_phone: str | None = None
    land_acres: Decimal | None = None
    scheme_name: str | None = None
    application_status: str | None = None
    subsidy_applied_inr: Decimal | None = None
    subsidy_approved_inr: Decimal | None = None
    subsidy_pending_inr: Decimal | None = None
    subsidy_received_inr: Decimal | None = None
    commission_earned_inr: Decimal | None = None
    follow_up_date: date | None = None
    notes: str | None = None


@router.patch("/subsidy/{case_id}", summary="Update agro subsidy case")
async def subsidy_patch(
    request: Request,
    case_id: int = Path(..., ge=1),
    body: SubsidyPatchBody | None = None,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    b = body or SubsidyPatchBody()
    payload = {k: v for k, v in b.model_dump().items() if v is not None}
    out = business_os_service.update_subsidy_case_sync(
        organization_id=_user.organization_id,
        case_id=case_id,
        **payload,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "update failed")
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="agro_subsidy_patch",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="agro_subsidy_case",
        extra={"case_id": case_id},
    )
    return {"status": "ok"}


@router.get("/tasks", summary="List business tasks and checklists")
async def business_tasks_list(
    limit: int = Query(200, ge=1, le=500),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    out = business_os_service.list_business_tasks_sync(organization_id=_user.organization_id, limit=limit)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return out


class BusinessTaskCreateBody(BaseModel):
    title: str = Field(..., min_length=1)
    owner_name: str = ""
    due_at: datetime | None = None
    task_type: str = "general"
    checklist_json: list[Any] | None = None


@router.post("/tasks", summary="Create business task")
async def business_tasks_create(
    request: Request,
    body: BusinessTaskCreateBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    out = business_os_service.create_business_task_sync(
        organization_id=_user.organization_id,
        title=body.title,
        owner_name=body.owner_name,
        due_at=body.due_at,
        task_type=body.task_type,
        checklist_json=body.checklist_json,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create failed")
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="business_task_create",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="business_task",
        extra={"task_id": out.get("id")},
    )
    return {"status": "ok", "id": out.get("id")}


class BusinessTaskPatchBody(BaseModel):
    title: str | None = None
    owner_name: str | None = None
    due_at: datetime | None = None
    status: str | None = None
    task_type: str | None = None
    checklist_json: list[Any] | None = None


@router.patch("/tasks/{task_id}", summary="Update business task or checklist")
async def business_tasks_patch(
    request: Request,
    task_id: int = Path(..., ge=1),
    body: BusinessTaskPatchBody | None = None,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    b = body or BusinessTaskPatchBody()
    payload = {k: v for k, v in b.model_dump().items() if v is not None}
    out = business_os_service.update_business_task_sync(
        organization_id=_user.organization_id,
        task_id=task_id,
        **payload,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "update failed")
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="business_task_patch",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="business_task",
        extra={"task_id": task_id},
    )
    return {"status": "ok"}


@router.get("/gst-suggest", summary="Upgrade 5: suggest GST % from HSN / description (India)")
async def business_gst_suggest(
    hsn: str = Query("", max_length=16),
    description: str = Query("", max_length=2000),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _require_auto_accounting(_user)
    from services.auto_accounting_service import gst_rate_from_hsn_sync

    _ = _user
    return {"ok": True, "suggestion": gst_rate_from_hsn_sync(hsn or None, description)}


@router.post("/import-bank-statement", summary="Upgrade 5: CSV or PDF bank statement → operational expenses")
async def business_import_bank_statement(
    request: Request,
    file: UploadFile = File(...),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _require_auto_accounting(_user)
    from services.auto_accounting_service import (
        extract_bank_transactions_from_text_sync,
        import_bank_statement_sync,
        parse_bank_statement_csv_sync,
        parse_bank_statement_pdf_sync,
    )

    raw = await file.read()
    from core.security.upload_validation import validate_upload_bytes

    vchk = validate_upload_bytes(
        raw,
        filename=file.filename or "statement",
        content_type=file.content_type,
        allowed_ext=("csv", "pdf"),
    )
    if not vchk.get("ok"):
        raise HTTPException(status_code=400, detail=vchk.get("error") or "invalid upload")
    name = (file.filename or "").lower()
    ct = (file.content_type or "").lower()
    txs: list[dict[str, Any]] = []
    if name.endswith(".csv") or "csv" in ct or "text/plain" in ct:
        parsed = parse_bank_statement_csv_sync(raw)
        if not parsed.get("ok"):
            raise HTTPException(status_code=400, detail=parsed.get("error") or "csv_parse_failed")
        txs = list(parsed.get("transactions") or [])
    elif name.endswith(".pdf") or "pdf" in ct:
        pdf = parse_bank_statement_pdf_sync(raw)
        if not pdf.get("ok"):
            raise HTTPException(status_code=400, detail=pdf.get("error") or "pdf_read_failed")
        extracted = extract_bank_transactions_from_text_sync(pdf.get("text") or "")
        if not extracted.get("ok"):
            raise HTTPException(status_code=400, detail=extracted.get("error") or "pdf_extract_failed")
        txs = list(extracted.get("transactions") or [])
    else:
        parsed = parse_bank_statement_csv_sync(raw)
        txs = list(parsed.get("transactions") or []) if parsed.get("ok") else []

    if not txs:
        raise HTTPException(status_code=400, detail="no transactions parsed")

    out = import_bank_statement_sync(
        organization_id=int(_user.organization_id),
        transactions=txs,
        user_id=int(_user.id),
    )
    try:
        from services.financial_audit_log_service import append_financial_audit_log_sync

        append_financial_audit_log_sync(
            action="bank_statement_import",
            user_id=int(_user.id),
            organization_id=int(_user.organization_id),
            entity_type="operational_expense_batch",
            before_state={"rows_in_file": len(txs)},
            after_state={"created": len(out.get("created") or []), "ok": out.get("ok")},
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        from core.operation_errors import log_subsystem_failure

        log_subsystem_failure(
            "financial_audit_log",
            exc,
            user_id=int(_user.id),
            organization_id=int(_user.organization_id),
            extra={"action": "bank_statement_import"},
        )
    audit_service.log_business_depth_mutation(
        correlation_id=_correlation_id(request),
        action_name="bank_statement_import",
        user_id=_user.id,
        organization_id=_user.organization_id,
        resource_type="operational_expense",
        extra={"rows": len(txs), "created": len(out.get("created") or [])},
    )
    return out
