"""Strategy generator APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.brain_execute import brain_execute
from services.strategy_generator_engine import generate_strategies, test_strategies

router = APIRouter(tags=["Strategy Generator"])


@router.get("/strategy-generator/generate")
async def get_strategy_generate(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return generate_strategies(int(user.id))


@router.post("/strategy-generator/test")
async def post_strategy_test(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    gen = generate_strategies(int(user.id))
    return test_strategies(int(user.id), int(user.organization_id), gen.get("items") or [])


@router.post("/strategy-generator/promote")
async def post_strategy_promote(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return brain_execute(
        "Promote best validated strategy",
        int(user.id),
        int(user.organization_id),
    )


@router.post("/strategy-generator/run")
async def post_strategy_run(
    user: CurrentUser = Depends(require_permission("manage_business", "trade_stock", "run_research")),
) -> dict[str, Any]:
    return brain_execute(
        "Generate and promote strategy",
        int(user.id),
        int(user.organization_id),
    )
