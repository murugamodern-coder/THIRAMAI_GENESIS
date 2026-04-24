"""Tool Builder Agent APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.tool_builder_agent import (
    deploy_tool,
    generate_tool_code,
    generate_tool_spec,
    sandbox_test_tool,
    tool_build_status,
)

router = APIRouter(tags=["Tool Builder"])


class ToolGenerateBody(BaseModel):
    goal_context: dict[str, Any] = Field(default_factory=dict)


@router.post("/tools/builder/generate")
async def post_tool_generate(
    body: ToolGenerateBody,
    user: CurrentUser = Depends(require_permission("build_apps", "manage_business")),
) -> dict[str, Any]:
    spec = generate_tool_spec(body.goal_context or {})
    if not spec.get("ok"):
        return spec
    built = generate_tool_code(spec, int(user.id))
    return {"ok": True, "spec": spec, "build": built}


@router.post("/tools/builder/{tool_id}/test")
async def post_tool_test(
    tool_id: str,
    user: CurrentUser = Depends(require_permission("build_apps", "manage_business")),
) -> dict[str, Any]:
    return sandbox_test_tool(str(tool_id), int(user.id))


@router.post("/tools/builder/{tool_id}/deploy")
async def post_tool_deploy(
    tool_id: str,
    user: CurrentUser = Depends(require_permission("build_apps", "manage_business")),
) -> dict[str, Any]:
    return deploy_tool(str(tool_id), int(user.id))


@router.get("/tools/builder/{tool_id}/status")
async def get_tool_status(
    tool_id: str,
    user: CurrentUser = Depends(require_permission("build_apps", "manage_business")),
) -> dict[str, Any]:
    return tool_build_status(str(tool_id), int(user.id))
