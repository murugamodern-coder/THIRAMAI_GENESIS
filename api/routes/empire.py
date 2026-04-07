"""Empire-level analytics routes (forecasts, multi-tenant)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api.dependencies import CurrentUser, require_roles
from services import predictive_engine

router = APIRouter(
    prefix="/empire",
    tags=["Empire"],
)


@router.get("/forecast")
async def empire_forecast(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    """
    Next-month **revenue** (from posted invoices) and **production / inventory-load index**
    (from production_logs via assets), using moving average + linear regression on monthly buckets.
    """
    try:
        payload = predictive_engine.compute_forecasts(organization_id=_user.organization_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(content=payload)
