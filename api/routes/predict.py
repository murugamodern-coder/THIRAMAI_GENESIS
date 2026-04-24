"""Predictive intelligence APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.predictive_engine import prediction_risk_alerts, prediction_summary

router = APIRouter(tags=["Predictive"])


@router.get("/predict/summary")
async def get_predict_summary(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return prediction_summary(int(user.id))


@router.get("/predict/risk-alerts")
async def get_predict_risk_alerts(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return prediction_risk_alerts(int(user.id))
