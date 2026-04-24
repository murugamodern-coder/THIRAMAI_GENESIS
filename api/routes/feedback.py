"""Feedback validation APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.feedback_engine import calculate_prediction_accuracy, feedback_drift

router = APIRouter(tags=["Feedback"])


@router.get("/feedback/accuracy")
async def get_feedback_accuracy(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return calculate_prediction_accuracy(int(user.id))


@router.get("/feedback/drift")
async def get_feedback_drift(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return feedback_drift(int(user.id))
