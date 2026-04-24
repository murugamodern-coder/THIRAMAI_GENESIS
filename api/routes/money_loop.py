"""Money loop control APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.brain_execute import brain_execute
from services.money_loop_engine import money_loop_status, upsert_money_loop_config
from services.opportunity_engine import list_opportunities
from services.profit_optimizer import allocate_capital

router = APIRouter(tags=["Money Loop"])


class MoneyLoopStartBody(BaseModel):
    max_daily_capital: float = Field(50000, ge=0)
    max_parallel_missions: int = Field(2, ge=1, le=20)
    risk_level: str = Field("medium", min_length=3, max_length=16)
    auto_execute: bool = False
    optimizer_enabled: bool = True
    run_now: bool = True


@router.post("/money-loop/start")
async def start_money_loop(
    body: MoneyLoopStartBody,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps")),
) -> dict[str, Any]:
    cfg = upsert_money_loop_config(
        user_id=int(user.id),
        enabled=True,
        max_daily_capital=float(body.max_daily_capital),
        max_parallel_missions=int(body.max_parallel_missions),
        risk_level=str(body.risk_level or "medium"),
        auto_execute=bool(body.auto_execute),
        optimizer_enabled=bool(body.optimizer_enabled),
    )
    if cfg is None:
        raise HTTPException(status_code=500, detail="Unable to start money loop")
    cycle = None
    if body.run_now:
        cycle = brain_execute(
            "Run money loop cycle now",
            int(user.id),
            int(user.organization_id),
        )
    return {"ok": True, "config": cfg, "cycle": cycle}


@router.post("/money-loop/stop")
async def stop_money_loop(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps")),
) -> dict[str, Any]:
    cfg = upsert_money_loop_config(user_id=int(user.id), enabled=False)
    if cfg is None:
        raise HTTPException(status_code=500, detail="Unable to stop money loop")
    return {"ok": True, "config": cfg}


@router.get("/money-loop/status")
async def get_money_loop_status(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps")),
) -> dict[str, Any]:
    return money_loop_status(int(user.id))


@router.get("/optimizer/allocation-preview")
async def get_optimizer_allocation_preview(
    capital: float | None = None,
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "build_apps")),
) -> dict[str, Any]:
    cfg = money_loop_status(int(user.id)).get("config") or {}
    total_capital = float(capital if capital is not None else (cfg.get("max_daily_capital") or 50000))
    brain_execute(
        "Scan opportunities for allocation preview",
        int(user.id),
        int(user.organization_id),
    )
    opportunities = list_opportunities(user_id=int(user.id), limit=120)
    risk_level = str(cfg.get("risk_level") or "medium")
    risk_rank = {"low": 1, "medium": 2, "high": 3}
    max_risk = risk_rank.get(risk_level, 2)
    filtered = [
        o
        for o in opportunities
        if str(o.get("status") or "new") in {"new", "approved"}
        and risk_rank.get(str(o.get("risk_level") or "medium"), 2) <= max_risk
    ]
    allocation = allocate_capital(
        filtered[:20],
        total_capital=total_capital,
        user_id=int(user.id),
        max_capital_per_opportunity=total_capital / max(int(cfg.get("max_parallel_missions") or 1), 1),
    )
    return {"ok": True, "capital": total_capital, "items": allocation}
