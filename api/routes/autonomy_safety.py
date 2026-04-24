"""Production autonomy safety: global halt, trust, monitoring, and policy status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.autonomy_safety_layer import (
    get_system_trust_score,
    global_autonomy_halted,
    safety_monitoring_summary,
    set_global_autonomy_halt,
    suggest_autonomy_level_for_trust,
)

router = APIRouter(tags=["Autonomy Safety"])


class GlobalHaltBody(BaseModel):
    enabled: bool = True
    reason: str = Field(default="", max_length=500)
    ttl_sec: int = Field(
        default=0,
        ge=0,
        le=86400 * 7,
        description="Optional Redis TTL for halt flag; 0 = no expiry (until cleared)",
    )


@router.get("/autonomy/safety/status")
async def get_autonomy_safety_status(
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    tr = get_system_trust_score(int(user.id))
    return {
        "ok": True,
        "global_halt": global_autonomy_halted(),
        "system_trust_score": tr,
        "suggested_autonomy_level": suggest_autonomy_level_for_trust(tr),
        "policy": {
            "risk_auto_lt": 30,
            "risk_batch_30_70": True,
            "risk_explicit_gt_70": True,
        },
        "monitoring": safety_monitoring_summary(int(user.id), hours=24),
    }


@router.post("/autonomy/safety/global-halt")
async def post_autonomy_global_halt(
    body: GlobalHaltBody,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    """
    Emergency stop for all automation / action runs (governance enforces; Redis or env in ops).
    Also set ``THIRAMAI_GLOBAL_AUTONOMY_HALT=1`` on the server if Redis is unavailable.
    """
    r = f"{(body.reason or '').strip()} (by user {user.id})"
    out = set_global_autonomy_halt(bool(body.enabled), reason=r, ttl_sec=int(body.ttl_sec or 0))
    if not out.get("ok") and not out.get("message"):
        raise HTTPException(503, "Unable to set global halt (Redis/IO)")
    return {"ok": True, "global_halt": body.enabled, **{k: v for k, v in out.items() if k != "ok"}}
