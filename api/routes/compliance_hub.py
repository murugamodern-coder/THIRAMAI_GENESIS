"""
Phase 5 — statutory alerts, comms briefing, draft replies (read-heavy; mutations via existing flows).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, get_current_user
from services.compliance_service import ensure_compliance_notifications, list_upcoming_statutory_context
from services.notification_dispatcher import build_daily_briefing

router = APIRouter(prefix="/compliance", tags=["Compliance & Comms"])


def _low_stock_threshold() -> int:
    import os

    raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
    try:
        return max(0, min(10_000, int(raw)))
    except ValueError:
        return 5


@router.get("/daily-briefing", summary="JARVIS daily briefing + optional draft replies (refreshes statutory notifications)")
async def compliance_daily_briefing(
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_compliance_notifications(_user.organization_id)
    return build_daily_briefing(_user.organization_id, low_stock_threshold=_low_stock_threshold())


@router.get("/statutory-calendar", summary="Current month statutory template deadlines (not legal advice)")
async def statutory_calendar(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return {
        "ok": True,
        "organization_id": user.organization_id,
        "items": list_upcoming_statutory_context(),
    }
