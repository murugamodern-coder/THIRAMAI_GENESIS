"""Central execution API (legacy ``/execute`` forwards to ``brain_execute``)."""

from __future__ import annotations

import asyncio
from typing import Any
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_permission
from services.async_task_queue import enqueue_task
from services.brain_execute import brain_execute
from services.brain_execute_adapter import brain_to_execute_response_dict
from services.brain_execute_deprecation import warn_deprecated_execution_forwarded
from services.intent_classifier import classify_intent
from services.modular_execution_services import (
    BuildService,
    BusinessService,
    MoneyService,
    PersonalService,
    ResearchService,
    ServiceExecutionContext,
)
from services.execute_conversation_store import (
    list_conversation_messages,
    list_user_conversations,
    persist_execute_exchange,
)
from services.execute_mission_store import (
    MissionExecutionContext,
    mission_to_payload,
    run_mission_sequentially,
)

router = APIRouter(tags=["Central Execution"])


class ExecuteRequest(BaseModel):
    command: str = Field(..., min_length=3, max_length=4000)
    conversation_id: int | None = None


class ExecuteResponse(BaseModel):
    class ExecutionStep(BaseModel):
        id: str
        label: str
        status: Literal["pending", "running", "done", "error", "failed"]
        step_order: int | None = None
        result: Any = None

    type: Literal["execution", "mission"] = "execution"
    execution_id: str
    conversation_id: int | None = None
    mission_id: int | None = None
    intent: str
    steps: list[ExecutionStep]
    result: Any
    status: str
    lifecycle_state: Literal["assist", "blocked", "running", "retrying", "completed", "failed", "cancelled"] = "failed"


class ConversationSummary(BaseModel):
    id: int
    title: str
    created_at: str | None = None


class ConversationMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


_INTENT_PERMISSION = {
    "research": "run_research",
    "business": "manage_business",
    "personal": "view_personal",
    "trading": "trade_stock",
    "money": "trade_stock",
    "build": "build_apps",
}
_FALLBACK_SERVICES = {
    "personal": PersonalService,
    "business": BusinessService,
    "research": ResearchService,
    "trading": MoneyService,
    "money": MoneyService,
    "build": BuildService,
}


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    summary="Central execution API for Thiramai",
)
async def post_execute(
    body: ExecuteRequest,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")),
) -> ExecuteResponse:
    warn_deprecated_execution_forwarded("/execute")
    try:
        brain = await asyncio.to_thread(
            brain_execute,
            str(body.command).strip(),
            int(user.id),
            int(user.organization_id),
        )
    except Exception:
        brain = {
            "status": "error",
            "intent": "unknown",
            "result": {"ok": False, "error": "brain_execute_exception"},
        }
    raw_intent = str(brain.get("intent") or "").strip().lower()
    if not raw_intent or raw_intent == "unknown":
        fallback = classify_intent(str(body.command))
        brain["intent"] = "trading" if fallback == "money" else str(fallback)
    elif raw_intent == "money":
        brain["intent"] = "trading"
    need_perm = _INTENT_PERMISSION.get(str(brain.get("intent") or ""))
    if need_perm:
        checker = require_permission(need_perm)
        await checker(user)
    payload = brain_to_execute_response_dict(
        brain,
        conversation_id=body.conversation_id,
        command=str(body.command),
    )
    if str(payload.get("status") or "") != "success":
        svc_cls = _FALLBACK_SERVICES.get(str(payload.get("intent") or "").strip().lower())
        if svc_cls is not None:
            svc = svc_cls()
            svc_out = svc.execute(
                str(body.command),
                ServiceExecutionContext(
                    user_id=int(user.id),
                    organization_id=int(user.organization_id),
                    role_name=str(user.role_name or ""),
                ),
            )
            payload["status"] = "success" if str(svc_out.get("status") or "") == "success" else "error"
            payload["steps"] = list(svc_out.get("steps") or payload.get("steps") or [])
            payload["result"] = {"brain": brain, "fallback_service": svc_out, "command": str(body.command)}
    try:
        conversation_id = persist_execute_exchange(
            user_id=int(user.id),
            conversation_id=body.conversation_id,
            command=body.command,
            assistant_payload=payload,
        )
    except Exception:
        conversation_id = body.conversation_id
    payload["conversation_id"] = conversation_id
    return ExecuteResponse(**payload)


@router.post(
    "/mission/{mission_id}/approve",
    summary="Approve a mission and start sequential execution",
)
async def approve_mission(
    mission_id: int,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")),
) -> dict[str, Any]:
    existing = mission_to_payload(mission_id=int(mission_id), user_id=int(user.id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    if str(existing.get("status") or "") == "completed":
        return existing
    queued = enqueue_task(
        "mission_execute",
        {
            "mission_id": int(mission_id),
            "user_id": int(user.id),
            "organization_id": int(user.organization_id),
            "role_name": str(user.role_name or ""),
        },
    )
    if not queued.get("queued"):
        asyncio.create_task(
            asyncio.to_thread(
                run_mission_sequentially,
                mission_id=int(mission_id),
                ctx=MissionExecutionContext(
                    user_id=int(user.id),
                    organization_id=int(user.organization_id),
                    role_name=str(user.role_name or ""),
                ),
            )
        )
    latest = mission_to_payload(mission_id=int(mission_id), user_id=int(user.id))
    return latest or {"type": "mission", "mission_id": int(mission_id), "status": "running", "steps": []}


@router.get(
    "/mission/{mission_id}",
    summary="Fetch mission status and steps",
)
async def get_mission(
    mission_id: int,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")),
) -> dict[str, Any]:
    mission = mission_to_payload(mission_id=int(mission_id), user_id=int(user.id))
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.get(
    "/execute/conversations",
    response_model=list[ConversationSummary],
    summary="List execute conversations for current user",
)
async def get_execute_conversations(
    limit: int = 30,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")),
) -> list[ConversationSummary]:
    rows = list_user_conversations(user_id=int(user.id), limit=limit)
    return [ConversationSummary(**row) for row in rows]


@router.get(
    "/execute/conversations/{conversation_id}/messages",
    response_model=list[ConversationMessageOut],
    summary="Load messages in one execute conversation",
)
async def get_execute_conversation_messages(
    conversation_id: int,
    limit: int = 200,
    user: CurrentUser = Depends(require_permission("build_apps", "run_research", "manage_business", "view_personal", "trade_stock")),
) -> list[ConversationMessageOut]:
    rows = list_conversation_messages(
        user_id=int(user.id),
        conversation_id=int(conversation_id),
        limit=limit,
    )
    return [ConversationMessageOut(**row) for row in rows]
