"""
Control Tower: single JSON aggregate for owners (revenue, alerts, approvals, forecast).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user, require_roles
from core.db.provisioning import MASS_SUCCESS_AGRO_AGENCY_ID
from services import approval_store, financial_service, predictive_engine
from services.market_research_service import build_solar_dpr_dashboard_block
from services.organization_service import default_saas_modules_for_organization
from workers import alert_system

from services.usage_log_service import build_analytics_summary_sync, log_usage_sync

router = APIRouter(prefix="/analytics", tags=["Analytics & Control Tower"])


class UsageEventBody(BaseModel):
    """Client-reported product events (onboarding, page views, etc.)."""

    action: str = Field(..., min_length=1, max_length=128)
    metadata: dict[str, Any] | None = None


@router.get("/summary", summary="Usage + AI + revenue + alerts snapshot for the current org")
async def analytics_summary(
    days: int = 30,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> JSONResponse:
    """
    Rolling window (default 30 days): distinct active users from ``usage_logs``, event counts by action,
    AI decision row totals, revenue snapshot from bills analytics, and alert inbox summary.
    """
    d = max(1, min(int(days), 366))
    payload = await asyncio.to_thread(build_analytics_summary_sync, int(_user.organization_id), days=d)
    if not payload.get("ok"):
        raise HTTPException(status_code=503, detail=payload.get("error") or "analytics_unavailable")
    return JSONResponse(content=payload)


@router.post("/usage-event", summary="Record a client-side usage event (authenticated)")
async def analytics_usage_event(
    body: UsageEventBody,
    _user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    if int(_user.id) <= 0:
        raise HTTPException(status_code=400, detail="Valid user id required")
    await asyncio.to_thread(
        lambda: log_usage_sync(
            organization_id=int(_user.organization_id),
            user_id=int(_user.id),
            action=body.action.strip(),
            metadata=body.metadata,
        ),
    )
    return JSONResponse(content={"ok": True})


def build_master_dashboard(*, organization_id: int) -> dict[str, Any]:
    """
    Aggregate financial_service, alert_system, approval_store, predictive_engine for one tenant.
    Sections are best-effort: failures are captured per block without failing the whole payload.
    """
    oid = int(organization_id)
    now = datetime.now(timezone.utc).isoformat()

    revenue_block: dict[str, Any] = {"ok": True, "source": "financial_service"}
    try:
        full = financial_service.financial_performance_summary_for_organization(oid)
        revenue_block["total_revenue_inr"] = full.get("total_revenue_inr")
        revenue_block["invoice_rows_with_revenue_inr"] = full.get("invoice_rows_with_revenue_inr")
        revenue_block["total_weight_kg"] = full.get("total_weight_kg")
        revenue_block["tsi"] = full.get("tsi")
        revenue_block["cash_flow_radar"] = full.get("cash_flow_radar")
        revenue_block["procurement_alert"] = full.get("procurement_alert")
        if isinstance(full.get("daily_interest_accrual"), dict):
            revenue_block["daily_interest_accrual"] = full["daily_interest_accrual"]
    except Exception as exc:
        revenue_block["ok"] = False
        revenue_block["error"] = f"{type(exc).__name__}: {exc}"

    alerts_block: dict[str, Any]
    try:
        alerts_block = alert_system.list_active_alerts_for_organization(organization_id=oid, limit=100)
    except Exception as exc:
        alerts_block = {
            "ok": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "organization_id": oid,
            "unread_count": 0,
            "items": [],
        }

    approvals_block: dict[str, Any] = {"ok": True, "count": 0, "items": []}
    try:
        items = approval_store.list_pending(organization_id=oid)
        approvals_block["count"] = len(items)
        approvals_block["items"] = items
    except RuntimeError as exc:
        approvals_block["ok"] = False
        approvals_block["error"] = str(exc)
    except Exception as exc:
        approvals_block["ok"] = False
        approvals_block["error"] = f"{type(exc).__name__}: {exc}"

    forecast_block: dict[str, Any]
    try:
        forecast_block = predictive_engine.compute_forecasts(organization_id=oid)
        forecast_block["ok"] = True
    except RuntimeError as exc:
        forecast_block = {"ok": False, "error": str(exc)}
    except Exception as exc:
        forecast_block = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    out: dict[str, Any] = {
        "schema": "thiramai.master_dashboard.v1",
        "control_tower": True,
        "title": "Master Dashboard — Control Tower",
        "organization_id": oid,
        "generated_at_utc": now,
        "revenue": revenue_block,
        "active_alerts": alerts_block,
        "pending_approvals": approvals_block,
        "ai_forecast": forecast_block,
        "saas_modules": default_saas_modules_for_organization(oid),
    }
    if oid == int(MASS_SUCCESS_AGRO_AGENCY_ID):
        out["solar_dpr"] = build_solar_dpr_dashboard_block(organization_id=oid, force_refresh=False)
    return out


@router.get("/master-dashboard")
async def master_dashboard(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    """
    Owner/Manager **Control Tower**: indexed revenue & TSI (financial_service), unread notifications
    (alert_system), HITL queue (approval_store), next-month forecast (predictive_engine).
    """
    try:
        payload = build_master_dashboard(organization_id=_user.organization_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"master_dashboard_failed: {exc}") from exc
    return JSONResponse(content=payload)


@router.post("/solar-dpr-research/refresh")
async def solar_dpr_research_refresh(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    """Force new Tavily pulls for org **Mass Success Agro Agency** (id=2) only."""
    oid = int(_user.organization_id)
    if oid != int(MASS_SUCCESS_AGRO_AGENCY_ID):
        raise HTTPException(status_code=404, detail="solar_dpr_not_applicable_for_this_organization")

    def _run() -> dict[str, Any]:
        return build_solar_dpr_dashboard_block(organization_id=oid, force_refresh=True)

    block = await asyncio.to_thread(_run)
    return JSONResponse(content=block)
