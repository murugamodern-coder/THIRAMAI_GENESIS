"""Central Brain OS tile status — stub metrics for `/api/os/{key}/status` (command center dashboard).

Agentic workflow: **Plan → Approve → Execute** (`/api/agent/*`) backed by ``services.orchestrator``.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy import text

import httpx

from api.dependencies import CurrentUser, get_current_user, try_resolve_current_user_from_access_token
from core.redis_cache import get_redis
from core.database import get_session_factory
from services.conversation_memory import ConversationMemory
from core.stability.circuit_breaker import export_breaker_snapshots
from services.health_checker import OSHealthChecker

_log_agent = logging.getLogger("thiramai.api.agent")

_THIRAMAI_CHAT_SYSTEM_PROMPT = """
You are Thiramai, a Tamil AI assistant.

INPUT LANGUAGE RULES:
- User may type in Tanglish (Tamil written in English letters)
  Example: "vanakkam", "enna panreenga", "sollu", "nalla irukka"
- User may type in Tamil script: "வணக்கம்"
- User may type in English

OUTPUT RULES:
- ALWAYS respond in Tamil script (தமிழ்)
- Technical words stay in English:
  server, deploy, install, database, API, code, error
- Keep responses conversational and natural
- Do NOT translate technical terms

EXAMPLES:
User: "vanakkam, enna panreenga"
Thiramai: "வணக்கம்! நான் நலமாக இருக்கேன். நீங்கள் எப்படி இருக்கீங்க?"

User: "server la enna error varuthu"
Thiramai: "server-ல என்ன error வருதுன்னு சொல்லுங்க, நான் fix பண்றேன்."

User: "stock market epdi iruku"
Thiramai: "இன்றைய stock market-ல Nifty 50 நல்லா இருக்கு..."

User: "pip install pannu"
Thiramai: "pip install பண்றேன் தலைவா..."
"""

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
    attachment: dict[str, Any] | None = Field(
        None,
        description="Optional single attachment payload: {name, type, data(base64)}",
    )


class VaultSaveBody(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=200000)
    category: str = Field("general", max_length=64)
    tags: list[str] = Field(default_factory=list)


class BrainTtsBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    lang: str = Field("ta-IN", max_length=24)


def _ensure_project_vault_table() -> None:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    with factory() as session:
        try:
            session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS project_vault (
                        id BIGSERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        organization_id BIGINT NOT NULL,
                        project_name VARCHAR(255) NOT NULL,
                        content TEXT NOT NULL,
                        category VARCHAR(64) NOT NULL DEFAULT 'general',
                        tags TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
        except Exception:
            session.rollback()
            session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS project_vault (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        organization_id INTEGER NOT NULL,
                        project_name TEXT NOT NULL,
                        content TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'general',
                        tags TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        session.commit()


def _search_project_vault(*, user_id: int, query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    like = f"%{q.lower()}%"
    sql = text(
        """
        SELECT id, project_name, content, category, tags, created_at, updated_at
        FROM project_vault
        WHERE user_id = :user_id
          AND (
            LOWER(project_name) LIKE :like
            OR LOWER(content) LIKE :like
            OR LOWER(tags) LIKE :like
          )
        ORDER BY updated_at DESC
        LIMIT :lim
        """
    )
    with factory() as session:
        rows = session.execute(sql, {"user_id": int(user_id), "like": like, "lim": int(limit)}).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "vault_id": int(r["id"]),
                "project_name": str(r["project_name"] or ""),
                "content": str(r["content"] or ""),
                "category": str(r["category"] or "general"),
                "tags": [x for x in str(r["tags"] or "").split(",") if x],
                "created_at": str(r["created_at"]) if r.get("created_at") is not None else None,
                "updated_at": str(r["updated_at"]) if r.get("updated_at") is not None else None,
            }
        )
    return out


def _is_tool_like_command(command_text: str) -> bool:
    """Heuristic: route obvious tool requests to ACTION so Groq can pick shell/file/git/docker tools."""
    t = (command_text or "").strip().lower()
    needles = (
        "pip install",
        "pip list",
        "python -m ",
        "read file",
        "read the file",
        "show file",
        "contents of ",
        "cat ",
        "git status",
        "git log",
        "git diff",
        "restart server",
        "restart the server",
        "restart web",
        "restart worker",
        "docker restart",
        "compose restart",
    )
    return any(n in t for n in needles)


def _groq_select_agent_tool(command: str) -> dict[str, Any] | None:
    """Parse natural language into a single tool invocation via Groq JSON."""
    from services.research_common import groq_json_object_sync

    user_prompt = f"""User command: {command}
Available tools: shell, file_read, file_write, git, docker_restart
Which tool should I use? Return JSON:
{{"tool": "shell", "params": {{"command": "pip install fpdf"}}}}"""
    system = (
        "You route the user command to one autonomous server tool when it clearly matches. "
        "Return ONLY a JSON object with keys "
        '`tool` (shell|file_read|file_write|git|docker_restart|none) and '
        '`params` (object). '
        'For shell use params.command and optional params.timeout (seconds). '
        'For file_read use params.path. '
        'For file_write use params.path and params.content — prefer tool none unless the user supplied full content. '
        'For git use params.action as status|log|diff. '
        'For docker_restart use params.service as web or worker-jobs. '
        "Use tool none when the request is not a single clear tool call."
    )
    data = groq_json_object_sync(system=system, user_content=user_prompt, max_tokens=512)
    if not isinstance(data, dict):
        return None
    tool = str(data.get("tool") or "").strip().lower()
    if tool in ("none", "null", ""):
        return None
    raw_params = data.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    return {"tool": tool.replace("-", "_"), "params": params}


def _classify_three_level_route(command_text: str) -> tuple[str, str, str]:
    if _is_tool_like_command(command_text):
        return "ACTION", "AgenticOS", "/os/agentic-platform"
    t = (command_text or "").strip().lower()
    chat_keywords = (
        "என்ன",
        "what",
        "when",
        "எப்போ",
        "who",
        "யார்",
        "how many",
        "எத்தனை",
        "status",
        "நிலை",
    )
    mission_keywords = (
        "plan",
        "research",
        "பிளான்",
        "ஆராய்ச்சி",
        "analyze",
        "report",
        "அறிக்கை",
        "strategy",
    )
    action_keywords = (
        "fix",
        "build",
        "deploy",
        "create",
        "சரிபண்ணு",
        "உருவாக்கு",
        "code",
        "automate",
    )

    if any(k in t for k in action_keywords):
        return "ACTION", "AgenticOS", "/os/agentic-platform"
    if any(k in t for k in mission_keywords):
        return "MISSION", "ResearchOS", "/os/research"
    if any(k in t for k in chat_keywords):
        return "CHAT", "Groq Chat", "/dashboard"
    # Default to chat so short commands get instant response unless explicitly mission/action.
    return "CHAT", "Groq Chat", "/dashboard"


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


def _parse_dt_safe(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _task_is_pending(row: dict[str, Any]) -> bool:
    try:
        idx = int(row.get("current_step_index") or 0)
    except Exception:
        idx = 0
    fp = row.get("full_plan_json")
    if isinstance(fp, str):
        try:
            fp = json.loads(fp)
        except Exception:
            fp = {}
    steps = (fp or {}).get("steps") if isinstance(fp, dict) else []
    if not isinstance(steps, list) or not steps:
        return True
    if idx < len(steps):
        return True
    # If pointer moved past last step, still consider pending if statuses are not terminal.
    return any(
        isinstance(s, dict) and str(s.get("status") or "") not in ("completed", "skipped", "failed")
        for s in steps
    )


async def _compute_proactive_alerts(user: CurrentUser) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    uid = _uid(user)

    # a) Any OS unhealthy/degraded/offline.
    unhealthy: list[str] = []
    for os_key in sorted(_ALLOWED):
        try:
            h = await _HEALTH_CHECKER.check_os(os_key, user_id=uid)
            st = str(h.get("status") or "offline")
            if st != "healthy":
                unhealthy.append(f"{os_key}:{st}")
        except Exception:
            unhealthy.append(f"{os_key}:offline")
    if unhealthy:
        alerts.append(
            {
                "type": "os_health",
                "message": f"{len(unhealthy)} OS module(s) degraded/offline ({', '.join(unhealthy[:3])}{'...' if len(unhealthy) > 3 else ''})",
                "severity": "critical",
                "action_route": "/dashboard",
            }
        )

    # b) Pending missions older than 24h.
    fac = get_session_factory()
    if fac is not None:
        stale_count = 0
        now = datetime.now(timezone.utc)
        try:
            with fac() as session:
                rows = session.execute(
                    text(
                        """
                        SELECT task_id, updated_at, current_step_index, full_plan_json
                        FROM agent_tasks
                        WHERE user_id = :user_id
                        ORDER BY updated_at DESC
                        LIMIT 300
                        """
                    ),
                    {"user_id": uid},
                ).mappings().all()
            for r in rows:
                updated = _parse_dt_safe(r.get("updated_at"))
                if not updated:
                    continue
                if now - updated <= timedelta(hours=24):
                    continue
                if _task_is_pending(dict(r)):
                    stale_count += 1
            if stale_count > 0:
                alerts.append(
                    {
                        "type": "stale_pending_tasks",
                        "message": f"{stale_count} pending mission(s) older than 24 hours",
                        "severity": "warning",
                        "action_route": "/os/research",
                    }
                )
        except Exception:
            # Table may not exist yet in some environments.
            pass

    # c) Any worker circuit breaker open.
    try:
        snaps = export_breaker_snapshots()
        open_breakers = [s for s in snaps if str(s.get("state") or "").lower() == "open"]
        if open_breakers:
            alerts.append(
                {
                    "type": "circuit_breaker_open",
                    "message": f"{len(open_breakers)} worker circuit breaker(s) OPEN",
                    "severity": "critical",
                    "action_route": "/dashboard",
                }
            )
    except Exception:
        pass

    return alerts


@router.post("/api/brain/vault/save", summary="Save Project Vault memory entry")
async def save_project_vault_entry(
    body: VaultSaveBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ensure_project_vault_table()
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    tags_csv = ",".join(
        sorted(
            {
                str(t).strip()
                for t in (body.tags or [])
                if str(t).strip()
            }
        )
    )
    sql = text(
        """
        INSERT INTO project_vault (user_id, organization_id, project_name, content, category, tags, created_at, updated_at)
        VALUES (:user_id, :organization_id, :project_name, :content, :category, :tags, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """
    )
    params = {
        "user_id": _uid(user),
        "organization_id": int(user.organization_id),
        "project_name": body.project_name.strip(),
        "content": body.content.strip(),
        "category": (body.category or "general").strip() or "general",
        "tags": tags_csv,
    }
    with factory() as session:
        vault_id: int | None = None
        try:
            row = session.execute(sql, params).first()
            vault_id = int(row[0]) if row else None
        except Exception:
            session.rollback()
            session.execute(
                text(
                    """
                    INSERT INTO project_vault (user_id, organization_id, project_name, content, category, tags, created_at, updated_at)
                    VALUES (:user_id, :organization_id, :project_name, :content, :category, :tags, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                params,
            )
            row2 = session.execute(text("SELECT id FROM project_vault ORDER BY id DESC LIMIT 1")).first()
            vault_id = int(row2[0]) if row2 else None
        session.commit()
    return {"ok": True, "vault_id": vault_id}


@router.get("/api/brain/vault/search", summary="Search Project Vault entries")
async def search_project_vault(
    q: str = Query(..., min_length=1, max_length=512),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ensure_project_vault_table()
    items = _search_project_vault(user_id=_uid(user), query=q, limit=50)
    return {"ok": True, "items": items}


@router.get("/api/brain/proactive", summary="Proactive central brain alerts")
async def get_proactive_alerts(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    alerts = await _compute_proactive_alerts(user)
    return {"alerts": alerts}


@router.get("/api/brain/history", summary="Central Brain chat history (Redis, same tenant)")
async def get_brain_chat_history(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    redis_client = await get_redis()
    memory = ConversationMemory(redis_client, _uid(user), int(user.organization_id))
    messages = await memory.get_history(limit=20)
    return {"ok": True, "messages": messages}


@router.delete("/api/brain/history", summary="Clear Central Brain chat history for current user/org")
async def delete_brain_chat_history(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    redis_client = await get_redis()
    memory = ConversationMemory(redis_client, _uid(user), int(user.organization_id))
    await memory.clear()
    return {"ok": True, "cleared": True}


async def _collect_brain_notifications(org_id: int) -> list[dict[str, Any]]:
    """Aggregate Redis-backed notifications for the active organization."""
    redis_client = await get_redis()
    out: list[dict[str, Any]] = []
    if redis_client is None:
        return out
    stock_key = f"thiramai:stock_alert:{org_id}"
    stock_rows = await redis_client.lrange(stock_key, 0, 24)
    for raw in stock_rows:
        try:
            row = json.loads(raw)
            if isinstance(row, dict):
                out.append(row)
        except (json.JSONDecodeError, TypeError):
            out.append({"icon": "📊", "message": str(raw), "time": "", "type": "stock"})
    task_rows = await redis_client.lrange(f"thiramai:task_reminders:{org_id}", 0, 19)
    for raw in task_rows:
        try:
            row = json.loads(raw)
            if isinstance(row, dict):
                out.append(row)
        except (json.JSONDecodeError, TypeError):
            continue
    hc = await redis_client.get("thiramai:last_health_check")
    if hc:
        out.append(
            {
                "icon": "💚",
                "message": "Autonomous scheduler heartbeat OK",
                "time": str(hc),
                "type": "system",
            }
        )
    return out


@router.get("/api/brain/morning-brief", summary="Today's morning brief (Redis or on-demand)")
async def get_brain_morning_brief(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    from services.scheduler import fetch_or_generate_morning_brief

    return await fetch_or_generate_morning_brief(int(user.organization_id))


@router.get("/api/brain/notifications", summary="Pending brain notifications (stock, tasks, system)")
async def get_brain_notifications(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    items = await _collect_brain_notifications(int(user.organization_id))
    return {"ok": True, "notifications": items}


def _google_tts_voice_for_lang(lang_raw: str) -> tuple[str, str]:
    lc = (lang_raw or "ta-IN").strip().lower().replace("_", "-")
    if lc.startswith("ta"):
        return "ta-IN", "ta-IN-Standard-A"
    return "en-IN", "en-IN-Standard-A"


@router.post("/api/brain/tts", summary="Synthesize speech (Google Cloud TTS when configured)")
async def post_brain_tts(
    body: BrainTtsBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return MP3 ``audioContent`` base64 when ``GOOGLE_TTS_API_KEY`` is set; otherwise browser TTS fallback."""
    _ = _user
    api_key = (os.getenv("GOOGLE_TTS_API_KEY") or "").strip()
    if not api_key:
        return {
            "ok": True,
            "fallback_browser": True,
            "format": "browser",
            "audio_base64": "",
        }

    lang_code, voice_name = _google_tts_voice_for_lang(body.lang)
    gcs_payload = {
        "input": {"text": body.text.strip()[:5000]},
        "voice": {
            "languageCode": lang_code,
            "name": voice_name,
            "ssmlGender": "FEMALE",
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 0.95,
            "pitch": 0.0,
        },
    }
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={quote_plus(api_key)}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=gcs_payload)
            resp.raise_for_status()
            gcs_data = resp.json()
    except Exception as exc:
        _log_agent.warning("brain_tts Google Cloud request failed: %s", exc)
        return {
            "ok": False,
            "fallback_browser": True,
            "format": "browser",
            "audio_base64": "",
        }

    audio_b64 = str(gcs_data.get("audioContent") or "").strip()
    if not audio_b64:
        return {
            "ok": False,
            "fallback_browser": True,
            "format": "browser",
            "audio_base64": "",
        }

    return {
        "ok": True,
        "fallback_browser": False,
        "format": "mp3",
        "audio_base64": audio_b64,
    }


@router.post("/api/orchestrator/command", summary="Global command router -> orchestrator plan")
async def post_orchestrator_command(
    request: Request,
    body: OrchestratorCommandBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from services.orchestrator import create_plan_from_command
    from services.research_common import long_llm_sync
    from groq import Groq

    command = body.command.strip()
    redis_client = await get_redis()
    memory = ConversationMemory(redis_client, _uid(user), int(user.organization_id))
    await memory.add_message("user", command)
    attachment = body.attachment if isinstance(body.attachment, dict) else None
    att_type = str((attachment or {}).get("type") or "").strip().lower()
    att_data = str((attachment or {}).get("data") or "").strip()
    routing, routed_to, suggested_route = _classify_three_level_route(command)
    os_key = "research" if routing == "MISSION" else "agentic" if routing == "ACTION" else "research"
    corr = (request.headers.get("X-Correlation-ID") or "").strip() or str(uuid.uuid4())

    if att_type.startswith("image/") and att_data:
        proactive_alerts = await _compute_proactive_alerts(user)
        alerts_count = len(proactive_alerts)

        def _vision_describe_sync() -> str:
            key = (os.getenv("GROQ_API_KEY") or "").strip()
            if not key:
                return "Image analysis unavailable now: GROQ_API_KEY not configured."
            try:
                client = Groq(api_key=key)
                response = client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{att_type};base64,{att_data}",
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": command or "இந்த image-ல என்ன இருக்கு? விவரமா சொல்லு.",
                                },
                            ],
                        }
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                )
                text_out = (response.choices[0].message.content or "").strip()
                return text_out or "படத்தைப் பற்றிய தெளிவான விளக்கம் கிடைக்கவில்லை."
            except Exception as exc:
                return f"Image analysis failed: {exc}"

        vision_text = await asyncio.to_thread(_vision_describe_sync)
        await memory.add_message("thiramai", vision_text, routing="CHAT")
        decorated = f"{vision_text} (⚠️ {alerts_count} active alerts need attention)"
        return {
            "ok": True,
            "routing": "CHAT",
            "routed_to": "Groq Vision",
            "response": decorated,
            "suggested_route": "/dashboard",
            "show_inline": True,
            "alerts_count": alerts_count,
            "os_key": "chat",
            "task_id": None,
            "requires_approval": False,
        }

    if routing == "ACTION":
        picked = await asyncio.to_thread(_groq_select_agent_tool, command)
        if picked and picked.get("tool"):
            from api.routes.agent_tools import dispatch_agent_tool

            exec_result = dispatch_agent_tool(
                user=user,
                request=request,
                tool=str(picked.get("tool") or ""),
                params=dict(picked.get("params") or {}),
            )
            hard_fail = bool(exec_result.get("detail")) and "output" not in exec_result and "content" not in exec_result
            if hard_fail:
                err = str(exec_result.get("detail") or "Tool execution failed.")
                return {
                    "ok": False,
                    "routing": routing,
                    "routed_to": "Thiramai Tools",
                    "response": err[:8000],
                    "suggested_route": suggested_route,
                    "show_inline": True,
                    "tool_result": exec_result,
                    "os_key": "agentic",
                    "task_id": None,
                    "requires_approval": False,
                }

            text_out = ""
            if "output" in exec_result:
                text_out = str(exec_result.get("output") or "")
            elif "content" in exec_result:
                c = str(exec_result.get("content") or "")
                text_out = c[:4000] + (" …" if len(c) > 4000 else "")
            elif exec_result.get("restarted"):
                text_out = "Service restart completed."
            elif exec_result.get("written"):
                text_out = "File written successfully."
            else:
                text_out = json.dumps(exec_result, default=str)[:12000]
            proactive_alerts = await _compute_proactive_alerts(user)
            alerts_count = len(proactive_alerts)
            decorated = f"{text_out}\n\n(⚠️ {alerts_count} active alerts need attention)"
            return {
                "ok": True,
                "routing": routing,
                "routed_to": "Thiramai Tools",
                "response": decorated,
                "suggested_route": suggested_route,
                "show_inline": True,
                "tool_result": exec_result,
                "alerts_count": alerts_count,
                "os_key": "agentic",
                "task_id": None,
                "requires_approval": False,
            }

    if routing == "CHAT":
        _ensure_project_vault_table()
        vault_hits = _search_project_vault(user_id=_uid(user), query=command, limit=4)
        vault_context = "\n\n".join(
            [
                f"[{i+1}] {h.get('project_name','')}\nCategory: {h.get('category','general')}\nTags: {', '.join(h.get('tags') or [])}\n{str(h.get('content') or '')[:1400]}"
                for i, h in enumerate(vault_hits)
            ]
        )
        proactive_alerts = await _compute_proactive_alerts(user)
        alerts_count = len(proactive_alerts)

        hist_raw = await memory.get_history(limit=10)
        history_messages = memory.format_for_llm(hist_raw)
        if redis_client is None:
            history_messages = [{"role": "user", "content": command}]

        vault_section = vault_context or "No matching vault context found."

        def _groq_chat_with_history_sync() -> str:
            key = (os.getenv("GROQ_API_KEY") or "").strip()
            if not key:
                return ""
            sys_content = (
                _THIRAMAI_CHAT_SYSTEM_PROMPT.strip()
                + "\n\nCONVERSATION:\n"
                + "- Prior turns appear in message history below; stay consistent.\n\n"
                + "Project vault context (may be empty):\n"
                + vault_section
                + "\n\nActive proactive alerts count: "
                + str(alerts_count)
            )
            msgs = [{"role": "system", "content": sys_content}] + history_messages
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=msgs,
                max_tokens=500,
                temperature=0.35,
            )
            return (chat.choices[0].message.content or "").strip()

        response_text = await asyncio.to_thread(_groq_chat_with_history_sync)
        if not str(response_text or "").strip():
            response_text = await asyncio.to_thread(
                lambda: long_llm_sync(
                    _THIRAMAI_CHAT_SYSTEM_PROMPT.strip()
                    + "\n\nFollow INPUT/OUTPUT rules above. Use vault and alerts when relevant.",
                    (
                        f"User query:\n{command}\n\n"
                        f"Project vault context (may be empty):\n{vault_context or 'No matching vault context found.'}\n\n"
                        f"Active proactive alerts count: {alerts_count}"
                    ),
                    prefer_gemini=False,
                )
            )
        base_response = str(response_text or "No response available right now.")
        await memory.add_message("thiramai", base_response, routing="CHAT")
        decorated = f"{base_response} (⚠️ {alerts_count} active alerts need attention)"
        return {
            "ok": True,
            "routing": routing,
            "routed_to": routed_to,
            "response": decorated,
            "suggested_route": suggested_route,
            "show_inline": True,
            "vault_matches": [
                {"vault_id": h.get("vault_id"), "project_name": h.get("project_name"), "category": h.get("category")}
                for h in vault_hits
            ],
            "alerts_count": alerts_count,
            "os_key": "chat",
            "task_id": None,
            "requires_approval": False,
        }

    out = create_plan_from_command(
        command,
        user_id=_uid(user),
        organization_id=int(user.organization_id),
        os_key=os_key,
        correlation_id=corr[:128],
        execution_mode="paper",
    )
    response_text = (
        str(out.get("title") or "").strip()
        or str(out.get("message") or "").strip()
        or ("Mission created and ready for approval." if out.get("task_id") else "Command accepted.")
    )
    return {
        "ok": bool(out.get("ok", True)),
        "routing": routing,
        "routed_to": routed_to,
        "response": response_text,
        "suggested_route": suggested_route,
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
