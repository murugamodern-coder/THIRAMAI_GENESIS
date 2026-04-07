"""HITL approvals, production-log billing, and invoice PDF creation."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime

import asset_portal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.billing_policy import enforce_billing_tool_policy
from api.dependencies import CurrentUser, require_permission
from core.rbac import Permission
from factory.billing_tool import build_invoice_pdf, default_invoice_path
from services import approval_store
from services import audit_log as system_audit
from services import billing_guard
from services import billing_service
from services.billing_phase2_service import (
    create_structured_invoice_sync,
    gst_report_sync,
    list_invoices_sync,
    record_payment_sync,
)
from services import workflow_rules
from core.recursive_learning import context_from_approval_row, record_learning_log
from services.execution_engine import BRAIN_ACTION_INTENT_TYPE, queue_action_intent_for_hitl
from services.job_queue import schedule_brain_intent_job, schedule_invoice_job, use_db_job_queue
from workers import jobs as worker_jobs

router = APIRouter(tags=["Billing & HITL"])


def _request_correlation_id(request: Request) -> str | None:
    c = getattr(request.state, "correlation_id", None)
    return c if isinstance(c, str) and c.strip() else None


def _require_factory_billing_active(organization_id: int) -> None:
    if billing_guard.is_billing_paused(int(organization_id)):
        raise HTTPException(
            status_code=503,
            detail=billing_guard.billing_pause_message(int(organization_id))
            or "Factory billing is paused (Stage 2 machine hold).",
        )


class BillingFromProductionLogBody(BaseModel):
    """Queue a Sovereign Billing run from a pipe-style production_logs row (HITL unless bypass env)."""

    production_log_id: int = Field(..., ge=1)
    buyer: str = Field(..., min_length=1)
    buyer_address: str = ""
    buyer_gstin: str = ""
    rate_per_kg: float = Field(..., gt=0)
    gst_percent: float = Field(default=18.0, ge=0)
    seller_name: str = "Your legal business name"
    seller_address: str = ""
    seller_gstin: str = ""
    sku_name: str = Field(..., min_length=1, description="inventory.sku_name to deduct (e.g. Pipe-HDPE-INV-1)")
    inventory_location: str = Field(default="", description="Must match inventory.location if set")
    length_m: float = Field(default=1.0, gt=0)
    grade: str = "HDPE"
    force_despite_gst_warnings: bool = False


class ApprovalResolveBody(BaseModel):
    confirm: str = Field(..., description="Type YES exactly (Sovereign Control) to approve high-risk action")
    feedback: str = Field(
        default="",
        max_length=4000,
        description="Optional note stored in learning_logs (why you approved/rejected; helps the brain avoid repeating mistakes).",
    )


class QueueBrainIntentBody(BaseModel):
    """Stage-5 ``action_intent`` from the brain; queued for Owner/Manager approval before execution."""

    action_intent: dict = Field(..., description="Validated action_intent JSON (e.g. update_stock, create_invoice)")


class ErpBillingCreateBody(BaseModel):
    """Register a simple invoice + ledger row when below approval threshold."""

    grand_total_inr: float = Field(..., ge=0)
    invoice_no: str = ""
    invoice_date: str = Field("", description="YYYY-MM-DD; default today UTC date")
    external_ref: str = ""


class InvoiceCreateBody(BaseModel):
    length: float = Field(..., gt=0, description="Pipe length (m)")
    grade: str = Field(..., min_length=1, description="Material grade e.g. HDPE PE100")
    weight: float = Field(..., gt=0, description="Weight kg")
    rate: float = Field(..., gt=0, description="INR per kg")
    buyer: str = "Buyer"
    buyer_address: str = ""
    invoice_no: str = ""
    invoice_date: str = ""
    gst: float = 18.0
    seller: str = "Your legal business name"
    seller_address: str = ""
    seller_gstin: str = ""


@router.post("/billing/create")
async def billing_create_simple(
    body: ErpBillingCreateBody,
    _user: CurrentUser = Depends(require_permission(Permission.BILLING_INVOICE_CREATE)),
) -> JSONResponse:
    """
    ERP invoice header + ledger posting. If ``grand_total_inr`` exceeds
    ``THIRAMAI_INVOICE_APPROVAL_THRESHOLD_INR`` (default ₹100,000), queues HITL instead of posting.
    """
    _require_factory_billing_active(_user.organization_id)
    grand = float(body.grand_total_inr)
    inv_date: date | None = None
    raw_d = (body.invoice_date or "").strip()
    if raw_d:
        try:
            parts = raw_d.split("-")
            if len(parts) == 3:
                inv_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            raise HTTPException(status_code=400, detail="invoice_date must be YYYY-MM-DD") from None

    if workflow_rules.invoice_requires_approval(grand):
        summary = (
            f"ERP invoice ₹{grand:,.2f} exceeds approval threshold "
            f"₹{workflow_rules.invoice_approval_threshold_inr():,.2f}"
        )
        inv_no = (body.invoice_no or "").strip() or f"PENDING-{date.today().isoformat()}"
        try:
            approval_id = approval_store.create_pending(
                organization_id=_user.organization_id,
                action_type="erp_simple_invoice",
                risk_tier=approval_store.RiskTier.high,
                payload={
                    "grand_total_inr": grand,
                    "invoice_no": inv_no,
                    "invoice_date": (inv_date or date.today()).isoformat(),
                    "external_ref": (body.external_ref or "").strip()[:512],
                    "requested_by_user_id": int(_user.id) if _user.id > 0 else None,
                },
                summary=summary,
                created_by=_user.id if _user.id > 0 else None,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(
            status_code=202,
            content={
                "ok": False,
                "pending_approval": True,
                "approval_id": approval_id,
                "detail": summary,
                "threshold_inr": workflow_rules.invoice_approval_threshold_inr(),
            },
        )

    out = billing_service.create_simple_erp_invoice_sync(
        _user.organization_id,
        invoice_no=(body.invoice_no or "").strip(),
        invoice_date=inv_date,
        grand_total_inr=grand,
        user_id=_user.id if _user.id > 0 else None,
        external_ref=(body.external_ref or "").strip() or None,
        post_ledger=True,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create invoice failed")
    return JSONResponse(content=out)


@router.get("/actions/pending-approvals")
async def list_pending_approvals(
    _user: CurrentUser = Depends(require_permission(Permission.HITL_APPROVE)),
) -> JSONResponse:
    """Human-in-the-loop queue (invoices, future email/GST). Scoped to caller's org."""
    try:
        items = approval_store.list_pending(organization_id=_user.organization_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(content={"items": items})


@router.post("/actions/billing/from-production-log")
async def action_billing_from_production_log(
    request: Request,
    body: BillingFromProductionLogBody,
    background_tasks: BackgroundTasks,
    _user: CurrentUser = Depends(require_permission(Permission.BILLING_MANAGE)),
) -> JSONResponse:
    """
    Draft GST breakdown from DB production log + queue invoice after Sovereign YES.
    Set SOVEREIGN_BYPASS_HITL=1 only in controlled dev to skip approval gate.
    """
    _require_factory_billing_active(_user.organization_id)
    enforce_billing_tool_policy(
        request,
        _user,
        tool_id="billing.production_log_invoice",
        action_name="production_log_invoice",
    )
    try:
        payload = billing_service.build_sale_payload_from_production_log(
            body.production_log_id,
            organization_id=_user.organization_id,
            buyer=body.buyer,
            buyer_address=body.buyer_address,
            rate_per_kg=body.rate_per_kg,
            gst_percent=body.gst_percent,
            seller_name=body.seller_name,
            seller_address=body.seller_address,
            seller_gstin=body.seller_gstin,
            sku_name=body.sku_name,
            inventory_location=body.inventory_location,
            length_m=body.length_m,
            grade=body.grade,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.buyer_gstin.strip():
        payload["buyer_gstin"] = body.buyer_gstin.strip()
    if body.force_despite_gst_warnings:
        payload["force_despite_gst_warnings"] = True
    payload["organization_id"] = _user.organization_id
    draft = billing_service.draft_invoice_from_db_sale(payload)
    bypass = (os.getenv("SOVEREIGN_BYPASS_HITL") or "").strip() == "1"
    if bypass:
        idem = f"invoice:prodlog:{body.production_log_id}"
        schedule_invoice_job(
            background_tasks,
            organization_id=_user.organization_id,
            idempotency_key=idem,
            invoice_payload=payload,
            approval_id=None,
            user_feedback="",
            resolved_by_user_id=None,
            job_fn=worker_jobs.job_execute_approved_invoice,
            correlation_id=_request_correlation_id(request),
        )
        return JSONResponse(
            {
                "status": "queued",
                "hitl_bypass": True,
                "idempotency_key": idem,
                "draft": draft,
                "job_queue": "db" if use_db_job_queue() else "inline",
            }
        )
    try:
        aid = approval_store.create_pending(
            organization_id=_user.organization_id,
            action_type="issue_invoice",
            risk_tier=approval_store.RiskTier.high,
            payload=payload,
            summary=(
                f"Invoice from production_log_id={body.production_log_id} buyer={body.buyer} "
                f"grand≈₹{draft['totals']['grand_total_inr']}"
            ),
            created_by=_user.id if _user.id > 0 else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(
        {
            "status": "pending_approval",
            "approval_id": aid,
            "draft": draft,
            "message": 'POST /actions/approvals/{id}/resolve with {"confirm":"YES"} to execute.',
        }
    )


@router.post("/actions/brain-intent/queue")
async def queue_brain_action_intent(
    request: Request,
    body: QueueBrainIntentBody,
    _user: CurrentUser = Depends(require_permission(Permission.HITL_APPROVE)),
) -> JSONResponse:
    """
    Human-in-the-loop gate for Stage-5 actions: validates ``action_intent`` and creates a pending approval.
    Execution runs only after ``POST /actions/approvals/{id}/resolve`` with ``{"confirm":"YES"}``.
    """
    enforce_billing_tool_policy(
        request,
        _user,
        tool_id="billing.queue_brain_intent",
        action_name="queue_brain_intent",
    )
    result = queue_action_intent_for_hitl(
        organization_id=_user.organization_id,
        action_intent=body.action_intent,
        created_by_user_id=_user.id if _user.id > 0 else None,
    )
    status = result.get("status")
    if status == "invalid":
        raise HTTPException(status_code=400, detail=result.get("message", "invalid action_intent"))
    code = 200 if status in ("pending_approval", "no_action") else 400
    return JSONResponse(content=result, status_code=code)


@router.post("/actions/approvals/{approval_id}/resolve")
async def resolve_approval_action(
    request: Request,
    approval_id: str,
    body: ApprovalResolveBody,
    background_tasks: BackgroundTasks,
    _user: CurrentUser = Depends(require_permission(Permission.HITL_APPROVE)),
) -> JSONResponse:
    # Policy + factory hold **before** DB marks approved (avoid orphaned approved rows on BLOCK).
    if (body.confirm or "").strip().upper() == "YES":
        pending_row = approval_store.get_approval(
            approval_id,
            organization_id=_user.organization_id,
        )
        if (
            pending_row
            and pending_row.get("status") == approval_store.ApprovalStatus.pending.value
        ):
            action_type_pre = pending_row.get("action_type") or ""
            if action_type_pre == "issue_invoice":
                _require_factory_billing_active(_user.organization_id)
            if action_type_pre == BRAIN_ACTION_INTENT_TYPE:
                enforce_billing_tool_policy(
                    request,
                    _user,
                    tool_id="billing.apply_approved_brain_intent_job",
                    action_name="apply_approved_brain_intent_job",
                )
            elif action_type_pre == "issue_invoice":
                enforce_billing_tool_policy(
                    request,
                    _user,
                    tool_id="billing.apply_approved_invoice_job",
                    action_name="apply_approved_invoice_job",
                )

    try:
        ok, row, msg = approval_store.resolve(
            approval_id,
            organization_id=_user.organization_id,
            sovereign_confirm=body.confirm,
            approved_by_user_id=_user.id if _user.id > 0 else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not ok or row is None:
        raise HTTPException(status_code=404, detail=msg)

    if row.get("status") != approval_store.ApprovalStatus.approved.value:
        if row.get("status") == approval_store.ApprovalStatus.rejected.value:
            try:
                record_learning_log(
                    organization_id=_user.organization_id,
                    outcome="rejected",
                    action_type=str(row.get("action_type") or ""),
                    context=context_from_approval_row(row),
                    result={"resolve_message": msg},
                    user_feedback=(body.feedback or "").strip(),
                    approval_id=str(row.get("id") or ""),
                    resolved_by_user_id=_user.id if _user.id > 0 else None,
                )
            except Exception:
                pass
        return JSONResponse({"status": row.get("status"), "message": msg})
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="approval payload missing")
    action_type = row.get("action_type") or ""
    if action_type == BRAIN_ACTION_INTENT_TYPE:
        idem = f"brain_intent:approval:{approval_id}"
        schedule_brain_intent_job(
            background_tasks,
            organization_id=_user.organization_id,
            idempotency_key=idem,
            intent_payload=payload,
            approval_id=approval_id,
            user_feedback=(body.feedback or "").strip(),
            resolved_by_user_id=_user.id if _user.id > 0 else None,
            job_fn=worker_jobs.job_execute_brain_intent,
            correlation_id=_request_correlation_id(request),
        )
        return JSONResponse(
            {
                "status": "queued_execution",
                "approval_id": approval_id,
                "idempotency_key": idem,
                "action_type": action_type,
                "job_queue": "db" if use_db_job_queue() else "inline",
                "message": "Brain intent job scheduled; inventory or invoice side effects run after response.",
            }
        )
    idem = f"invoice:approval:{approval_id}"
    schedule_invoice_job(
        background_tasks,
        organization_id=_user.organization_id,
        idempotency_key=idem,
        invoice_payload=payload,
        approval_id=approval_id,
        user_feedback=(body.feedback or "").strip(),
        resolved_by_user_id=_user.id if _user.id > 0 else None,
        job_fn=worker_jobs.job_execute_approved_invoice,
        correlation_id=_request_correlation_id(request),
    )
    return JSONResponse(
        {
            "status": "queued_execution",
            "approval_id": approval_id,
            "idempotency_key": idem,
            "action_type": action_type,
            "job_queue": "db" if use_db_job_queue() else "inline",
            "message": "Invoice job scheduled after response; check factory_output and master_index.csv",
        }
    )


@router.post("/assets/invoice")
async def create_invoice_pdf(
    request: Request,
    body: InvoiceCreateBody,
    _user: CurrentUser = Depends(require_permission(Permission.BILLING_MANAGE)),
) -> JSONResponse:
    """Generate dated invoice PDF, append master_index.csv, return view URL (cursor synced so /chat won't duplicate)."""
    _require_factory_billing_active(_user.organization_id)
    enforce_billing_tool_policy(
        request,
        _user,
        tool_id="billing.generate_invoice_pdf",
        action_name="generate_invoice_pdf",
    )
    inv_date = (body.invoice_date or "").strip() or date.today().isoformat()
    inv_no = (body.invoice_no or "").strip() or f"INV-{inv_date.replace('-', '')}-01"
    out = default_invoice_path()
    try:
        path = build_invoice_pdf(
            buyer_name=body.buyer,
            buyer_address=body.buyer_address or "-",
            invoice_no=inv_no,
            invoice_date=inv_date,
            length_m=body.length,
            grade=body.grade,
            weight_kg=body.weight,
            rate_per_kg=body.rate,
            gst_percent=body.gst,
            seller_name=body.seller,
            seller_address=body.seller_address or "-",
            seller_gstin=body.seller_gstin or "-",
            out_path=out,
            organization_id=_user.organization_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invoice PDF generation failed: {type(exc).__name__}: {exc}",
        ) from exc
    rel = path.relative_to(asset_portal.FACTORY_OUTPUT.resolve()).as_posix()
    subtotal = body.weight * body.rate
    gst_amt = subtotal * (body.gst / 100.0)
    grand = subtotal + gst_amt
    asset_portal.append_sales_history_entry(
        {
            "invoice_no": inv_no,
            "invoice_date": inv_date,
            "relative_path": rel,
            "buyer": body.buyer,
            "buyer_address": body.buyer_address,
            "length_m": body.length,
            "grade": body.grade,
            "weight_kg": body.weight,
            "rate_per_kg_inr": body.rate,
            "gst_percent": body.gst,
            "subtotal_inr": round(subtotal, 2),
            "gst_inr": round(gst_amt, 2),
            "grand_total_inr": round(grand, 2),
            "seller": body.seller,
            "seller_gstin": body.seller_gstin,
        }
    )
    url = asset_portal.factory_url_for_relative(rel)
    asset_portal.sync_index_cursor_to_end()
    system_audit.record_system_audit(
        action=system_audit.ACTION_FINANCIAL_EXECUTION,
        outcome="success",
        organization_id=_user.organization_id,
        user_id=_user.id if _user.id > 0 else None,
        resource_type="invoice",
        metadata={
            "invoice_no": inv_no[:64],
            "grand_total_inr": round(grand, 2),
            "source": "api_assets_invoice",
        },
    )
    quick_actions = [{"label": "View Invoice", "url": url, "kind": "pdf"}]
    return JSONResponse(
        content={
            "response": "Invoice created successfully",
            "quick_actions": quick_actions,
            "ok": True,
            "relative_path": rel,
        }
    )


# --- Phase 2: structured invoices, payments, GST report ---


class StructuredInvoiceLineBody(BaseModel):
    description: str = ""
    quantity: float = Field(..., gt=0)
    unit_price_pre_tax: float = Field(..., ge=0)
    gst_rate_percent: float = Field(0, ge=0)
    hsn_code: str | None = None


class StructuredInvoiceBody(BaseModel):
    invoice_no: str = ""
    invoice_date: str = Field("", description="YYYY-MM-DD; default today")
    external_ref: str | None = None
    lines: list[StructuredInvoiceLineBody] = Field(..., min_length=1)


def _parse_iso_date(raw: str | None) -> date | None:
    if not (raw or "").strip():
        return None
    try:
        parts = raw.strip().split("-")
        if len(parts) != 3:
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


@router.post("/billing/invoice")
async def billing_phase2_create_invoice(
    body: StructuredInvoiceBody,
    _user: CurrentUser = Depends(require_permission(Permission.BILLING_INVOICE_CREATE)),
) -> JSONResponse:
    """Create invoice with line items; GST computed per line (taxable + GST = line_total_inr)."""
    _require_factory_billing_active(_user.organization_id)
    inv_date = _parse_iso_date(body.invoice_date) or date.today()
    out = create_structured_invoice_sync(
        organization_id=_user.organization_id,
        invoice_no=body.invoice_no,
        invoice_date=inv_date,
        lines=[ln.model_dump() for ln in body.lines],
        external_ref=body.external_ref,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "invoice create failed")
    await asyncio.to_thread(
        lambda: log_usage_sync(
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            action=ACTION_INVOICE_CREATE,
            metadata={
                "invoice_id": out.get("invoice_id"),
                "invoice_no": out.get("invoice_no"),
                "grand_total_inr": out.get("grand_total_inr"),
            },
        ),
    )
    return JSONResponse(content=out)


@router.get("/billing/invoices")
async def billing_phase2_list_invoices(
    limit: int = 200,
    _user: CurrentUser = Depends(
        require_permission(Permission.BILLING_MANAGE, Permission.BILLING_INVOICE_CREATE)
    ),
) -> JSONResponse:
    out = list_invoices_sync(organization_id=_user.organization_id, limit=limit)
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "list failed")
    return JSONResponse(content=out)


class PaymentRecordBody(BaseModel):
    invoice_id: int = Field(..., ge=1)
    amount_inr: float = Field(..., gt=0)
    method: str = "bank"
    reference: str | None = None
    paid_at: str | None = Field(None, description="ISO-8601 datetime; default now UTC")


@router.post("/billing/payment")
async def billing_phase2_record_payment(
    body: PaymentRecordBody,
    _user: CurrentUser = Depends(require_permission(Permission.BILLING_MANAGE)),
) -> JSONResponse:
    _require_factory_billing_active(_user.organization_id)
    paid: datetime | None = None
    if body.paid_at and body.paid_at.strip():
        try:
            paid = datetime.fromisoformat(body.paid_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="paid_at must be ISO-8601") from None
    out = record_payment_sync(
        organization_id=_user.organization_id,
        invoice_id=body.invoice_id,
        amount_inr=body.amount_inr,
        method=body.method,
        reference=body.reference,
        paid_at=paid,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "payment failed")
    return JSONResponse(content=out)


@router.get("/billing/gst-report")
async def billing_phase2_gst_report(
    period_start: str = Query(..., description="YYYY-MM-DD"),
    period_end: str = Query(..., description="YYYY-MM-DD"),
    _user: CurrentUser = Depends(require_permission(Permission.BILLING_MANAGE)),
) -> JSONResponse:
    ps = _parse_iso_date(period_start)
    pe = _parse_iso_date(period_end)
    if ps is None or pe is None:
        raise HTTPException(status_code=400, detail="period_start and period_end must be YYYY-MM-DD")
    out = gst_report_sync(
        organization_id=_user.organization_id,
        period_start=ps,
        period_end=pe,
        user_id=_user.id if _user.id > 0 else None,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "gst report failed")
    return JSONResponse(content=out)
