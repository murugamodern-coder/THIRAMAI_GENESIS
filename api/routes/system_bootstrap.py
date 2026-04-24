"""System bootstrap and runtime health APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from api.dependencies import CurrentUser, require_permission
from services.governance_engine import set_kill_switch
from services.money_loop_engine import upsert_money_loop_config
from services.revenue_engine import revenue_snapshot
from services.system_bootstrap_engine import bootstrap_system, runtime_health

router = APIRouter(tags=["System Bootstrap"])


@router.post("/system/bootstrap")
async def post_system_bootstrap(
    request: Request,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    return await bootstrap_system(
        app=request.app,
        user_id=int(user.id),
        organization_id=int(user.organization_id),
    )


@router.get("/system/runtime-health")
async def get_system_runtime_health(
    request: Request,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    out = runtime_health(app=request.app, user_id=int(user.id))
    out["revenue_today"] = revenue_snapshot(int(user.id), 24).get("total", 0)
    return out


@router.post("/system/emergency-stop")
async def post_system_emergency_stop(
    request: Request,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock")),
) -> dict[str, Any]:
    set_kill_switch(int(user.id), enabled=True, reason="Emergency stop from war room")
    upsert_money_loop_config(user_id=int(user.id), enabled=False)
    sch = getattr(request.app.state, "scheduler", None)
    if sch is not None and bool(getattr(sch, "running", False)):
        await sch.stop()
    return {"ok": True, "stopped": True}
