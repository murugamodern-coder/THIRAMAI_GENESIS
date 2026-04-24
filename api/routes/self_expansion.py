"""Self-expansion engine APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import CurrentUser, require_permission
from services.self_expansion_engine import detect_capability_gaps, run_self_expansion

router = APIRouter(tags=["Self Expansion"])


@router.get("/self-expansion/gaps")
async def get_self_expansion_gaps(
    user: CurrentUser = Depends(require_permission("build_apps", "manage_business", "run_research")),
) -> dict[str, Any]:
    return detect_capability_gaps(int(user.id))


@router.post("/self-expansion/run")
async def post_self_expansion_run(
    user: CurrentUser = Depends(require_permission("build_apps", "manage_business", "run_research")),
) -> dict[str, Any]:
    return run_self_expansion(int(user.id))
