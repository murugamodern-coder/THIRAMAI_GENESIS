"""Central Brain OS tile status — stub metrics for `/api/os/{key}/status` (command center dashboard).

Agentic workflow: **Plan → Approve → Execute** (`/api/agent/*`) backed by ``services.orchestrator``.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from api.dependencies import CurrentUser, get_current_user, try_resolve_current_user_from_access_token
from services.health_checker import OSHealthChecker

_log_agent = logging.getLogger("thiramai.api.agent")

router = APIRouter(tags=["Central Brain", "Agentic workflow"])

_ALLOWED = frozenset({"personal", "business", "stock", "research", "agentic"})
_SYSTEM_LOG_RING: deque[dict[str, Any]] = deque(maxlen=400)
_SYSTEM_LOG_HANDLER_ATTACHED = False
_HEALTH_CHECKER = OSHealthChecker()


class _SystemLogRingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            lg = str(record.name or "")
            if "orchestrator" not in lg and "auto_deploy" not in lg:
                return
            _SYSTEM_LOG_RING.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "logger": lg,
                    "level": str(record.levelname),
                    "message": str(record.getMessage())[:1200],
                }
            )
        except Exception:
            return


def _attach_system_log_handler_once() -> None:
    global _SYSTEM_LOG_HANDLER_ATTACHED
    if _SYSTEM_LOG_HANDLER_ATTACHED:
        return
    h = _SystemLogRingHandler()
    for nm in ("thiramai.services.orchestrator", "thiramai.auto_deploy"):
        logging.getLogger(nm).addHandler(h)
    _SYSTEM_LOG_HANDLER_ATTACHED = True


@router.get("/api/os/{os_key}/status")
async def get_os_status(
    os_key: str,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    if os_key not in _ALLOWED:
        raise HTTPException(status_code=404, detail="Unknown OS module")
    h = await _HEALTH_CHECKER.check_os(os_key, user_id=int(_user.id))
    h_status = str(h.get("status") or "offline")
    status = "active" if h_status == "healthy" else h_status
    latency = int(h.get("latency_ms") or 0)
    reason = h.get("degraded_reason")
    metrics = {
        "health_score": 100 if h_status == "healthy" else 60 if h_status == "degraded" else 0,
        "latency_ms": latency,
        "healthy": 1 if h_status == "healthy" else 0,
        "degraded": 1 if h_status == "degraded" else 0,
        "offline": 1 if h_status == "offline" else 0,
    }
    # Legacy tile metric keys expected by frontend cards.
    if os_key == "personal":
        metrics["tasks_today"] = metrics["health_score"]
        metrics["focus_hours"] = max(0, 8 - min(8, latency // 200))
    elif os_key == "business":
        metrics["revenue_today"] = metrics["health_score"]
        metrics["invoices_open"] = 0 if h_status == "healthy" else 1
    elif os_key == "stock":
        metrics["signals_count"] = 1 if h_status != "offline" else 0
        metrics["risk_score"] = 100 - metrics["health_score"]
    elif os_key == "research":
        metrics["missions_active"] = 1 if h_status == "healthy" else 0
        metrics["reports_ready"] = 1 if h_status != "offline" else 0
    elif os_key == "agentic":
        metrics["projects_active"] = 1 if h_status != "offline" else 0
        metrics["deploys_today"] = 1 if h_status == "healthy" else 0
    config_badge: str | None = None
    if os_key == "stock":
        config_badge = "configured" if h_status == "healthy" else "missing_keys"
    if os_key == "research":
        config_badge = "configured" if h_status == "healthy" else "missing_keys"
    return {
        "osKey": os_key,
        "status": status,
        "metrics": metrics,
        "configBadge": config_badge,
        "health": {
            "status": h_status,
            "latency_ms": latency,
            "last_checked": h.get("last_checked"),
            "degraded_reason": reason,
        },
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _uid(user: CurrentUser) -> int:
    return int(user.id)


@router.websocket("/ws/system/logs")
async def ws_system_logs(websocket: WebSocket) -> None:
    _attach_system_log_handler_once()
    await websocket.accept()
    try:
        raw = await websocket.receive_text()
        token = None
        try:
            token = json.loads(raw or "{}").get("token")
        except Exception:
            token = None
        user = try_resolve_current_user_from_access_token(str(token or "").strip())
        if user is None:
            await websocket.send_json({"ok": False, "error": "unauthorized"})
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.send_json({"ok": True, "type": "ready"})
        idx = max(0, len(_SYSTEM_LOG_RING) - 40)
        while True:
            ring_snapshot = list(_SYSTEM_LOG_RING)
            while idx < len(ring_snapshot):
                await websocket.send_json({"ok": True, "type": "log", "entry": ring_snapshot[idx]})
                idx += 1
            await asyncio.sleep(0.8)
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            return


class AgentCommandBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=16000)
    os_key: str = Field("stock", description="Primary OS context (e.g. stock for Trading Edge)")
    execution_mode: str = Field("paper", description="paper | live (broker adapter; keys may still fall back to paper)")
    correlation_id: str | None = Field(
        None,
        max_length=128,
        description="Stable thread/mission id for dashboards (also accepted as X-Correlation-ID)",
    )


class AgentApproveBody(BaseModel):
    signal: str = Field("success", description="success | reject | cancel")
    execution_mode: str | None = Field(
        None,
        description="Optional: switch paper|live before running the next step",
    )


class OrchestratorCommandBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=16000)
    source: str = Field("global_bar", max_length=128)


def _classify_os_key(command_text: str) -> str:
    t = (command_text or "").strip().lower()
    if any(k in t for k in ("stock", "trade", "option", "nifty")):
        return "stock"
    if any(k in t for k in ("research", "news", "report", "video")):
        return "research"
    if any(k in t for k in ("code", "build", "deploy", "website")):
        return "agentic"
    if any(k in t for k in ("invoice", "gst", "business")):
        return "business"
    if any(k in t for k in ("calendar", "diet", "health", "personal")):
        return "personal"
    return "agentic"


@router.post("/api/orchestrator/command", summary="Global command router -> orchestrator plan")
async def post_orchestrator_command(
    request: Request,
    body: OrchestratorCommandBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from services.orchestrator import create_plan_from_command

    command = body.command.strip()
    os_key = _classify_os_key(command)
    corr = (request.headers.get("X-Correlation-ID") or "").strip() or str(uuid.uuid4())
    out = create_plan_from_command(
        command,
        user_id=_uid(user),
        organization_id=int(user.organization_id),
        os_key=os_key,
        correlation_id=corr[:128],
        execution_mode="paper",
    )
    return {
        "ok": bool(out.get("ok", True)),
        "os_key": os_key,
        "task_id": out.get("task_id"),
        "requires_approval": bool(out.get("requires_approval")),
    }


@router.post("/api/agent/command", summary="Create agentic plan from natural language (Groq JSON)")
async def post_agent_command(
    request: Request,
    body: AgentCommandBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    from services.orchestrator import create_plan_from_command

    corr = (
        (body.correlation_id or "").strip()
        or (request.headers.get("X-Correlation-ID") or "").strip()
        or ""
    )
    if not corr:
        corr = str(uuid.uuid4())
    out = create_plan_from_command(
        body.command.strip(),
        user_id=_uid(user),
        organization_id=int(user.organization_id),
        os_key=(body.os_key or "stock").strip().lower(),
        correlation_id=corr[:128],
        execution_mode=(body.execution_mode or "paper").strip().lower(),
    )
    if out.get("requires_approval"):
        _log_agent.info(
            "Jarvis awaits approval task_id=%s user_id=%s",
            out.get("task_id"),
            _uid(user),
        )
    return out


@router.get("/api/agent/plan/{task_id}", summary="Get plan state (approval queue)")
async def get_agent_plan(
    task_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    from services.orchestrator import get_plan

    got = get_plan(task_id.strip(), user_id=_uid(user))
    if not got:
        raise HTTPException(status_code=404, detail="plan not found")
    return got


@router.get("/api/agent/missions", summary="Recent agent missions (plan history by user)")
async def list_agent_missions(
    limit: int = Query(40, ge=1, le=100),
    os_key: str | None = Query(None, description="Filter e.g. research | stock"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    from services.agent_tasks_repo import list_tasks_for_user

    ok = (os_key or "").strip().lower() or None
    items = list_tasks_for_user(_uid(user), limit=int(limit), os_key=ok)
    return {"ok": True, "items": items}


def _plan_terminal(plan: dict[str, Any]) -> bool:
    steps = plan.get("steps") or []
    if not steps:
        return True
    pending = any(str(s.get("status") or "") == "pending_approval" for s in steps if isinstance(s, dict))
    if pending:
        return False
    return all(
        str(s.get("status") or "") in ("completed", "skipped", "failed") for s in steps if isinstance(s, dict)
    )


@router.get("/api/agent/plan/{task_id}/events", summary="SSE stream of plan snapshots (JWT via Authorization header)")
async def agent_plan_events_stream(
    task_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """Browser EventSource cannot send Bearer tokens; use fetch-stream reader from the SPA."""

    async def gen():
        uid = _uid(user)
        from services.orchestrator import get_plan

        for tick in range(840):
            if await request.is_disconnected():
                break
            got = get_plan(task_id.strip(), user_id=uid)
            if not got:
                yield f"data: {json.dumps({'ok': False, 'error': 'plan_not_found'})}\n\n"
                break
            envelope = dict(got)
            envelope["_sse_tick"] = tick
            yield f"data: {json.dumps(envelope, default=str)}\n\n"
            if got.get("ok") and _plan_terminal(got):
                await asyncio.sleep(0.35)
                break
            await asyncio.sleep(1.1)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.post("/api/agent/approve/{task_id}", summary="Approve/reject next pending step")
async def post_agent_approve(
    task_id: str,
    body: AgentApproveBody | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    from services.orchestrator import approve_and_advance

    payload = body or AgentApproveBody()
    return approve_and_advance(
        task_id.strip(),
        user_id=_uid(user),
        signal=payload.signal,
        execution_mode=payload.execution_mode,
    )
