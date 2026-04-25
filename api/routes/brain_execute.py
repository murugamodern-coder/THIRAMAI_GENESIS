"""Unified execution entry: intent → plan → ``execute_action_plan`` (single path)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.brain_execute import brain_execute
from services.research_common import groq_json_object_sync

router = APIRouter(tags=["Brain execute"])
_LOG = logging.getLogger(__name__)


class BrainExecuteRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=8000)
    user_id: int = Field(..., ge=1)
    organization_id: int = Field(..., ge=1)


def _rule_based_brain_summary(result: dict[str, Any], command: str) -> str:
    status = str(result.get("status") or "").lower()
    intent = str(result.get("intent") or "unknown")
    if status == "success":
        return f"Command executed successfully for intent '{intent}'."
    if status == "assist":
        return f"Command is in assist mode for intent '{intent}'. Review and confirm next action."
    if status == "blocked":
        return f"Execution was blocked by safety/governance for intent '{intent}'."
    return f"Execution finished with status '{status or 'failed'}' for intent '{intent}'."


def _attach_ai_summary(result: dict[str, Any], command: str) -> dict[str, Any]:
    out = dict(result)
    if not (os.getenv("GROQ_API_KEY") or "").strip():
        out["response_mode"] = "rule_based"
        out["ai_summary"] = _rule_based_brain_summary(out, command)
        return out

    model = (os.getenv("THIRAMAI_BRAIN_FAST_MODEL") or "llama-3.1-8b-instant").strip()
    parsed = groq_json_object_sync(
        system=(
            "You generate a concise operator summary for a business command execution response. "
            "Return strict JSON: {\"summary\":\"...\"} with max 220 chars."
        ),
        user_content=(
            f"Model preference: {model}\n"
            f"Command: {command[:500]}\n"
            f"Execution JSON: {str(out)[:6000]}"
        ),
        max_tokens=120,
    )
    summary = str((parsed or {}).get("summary") or "").strip()
    out["response_mode"] = "llm"
    out["ai_model"] = model
    out["ai_summary"] = summary or _rule_based_brain_summary(out, command)
    return out


@router.post("/brain/execute")
async def post_brain_execute(
    body: BrainExecuteRequest,
    user: CurrentUser = Depends(
        require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")
    ),
) -> dict[str, Any]:
    if int(body.user_id) != int(user.id) or int(body.organization_id) != int(user.organization_id):
        raise HTTPException(
            status_code=403,
            detail="user_id and organization_id must match the authenticated session",
        )
    cmd = str(body.command).strip()
    try:
        result = await asyncio.to_thread(
            brain_execute,
            cmd,
            int(user.id),
            int(user.organization_id),
        )
        return _attach_ai_summary(result if isinstance(result, dict) else {}, cmd)
    except HTTPException:
        raise
    except Exception as exc:
        _LOG.exception("brain_execute_unhandled_error")
        raise HTTPException(status_code=500, detail="Brain execute failed safely.") from exc
