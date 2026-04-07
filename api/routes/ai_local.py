"""
Unified **local** AI (Ollama): smart model routing + optional streaming.

Complements cloud ``/chat`` (Groq council). Does not change existing chat routes.
"""

from __future__ import annotations

import os

from fastapi import Depends, HTTPException
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from core.ai_model_router import PromptKind, classify_prompt_kind, ollama_model_for_kind
from services.ollama_unified import OllamaUnavailableError, ollama_chat_async, ollama_chat_stream, ollama_chat_sync

router = APIRouter(prefix="/ai/local", tags=["Unified local AI"])

_SYSTEM = (
    "You are THIRAMAI, a concise business and personal assistant. "
    "Prefer short actionable answers unless the user asked for detail."
)


def _local_ai_enabled() -> bool:
    return (os.getenv("THIRAMAI_LOCAL_AI_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class LocalChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=12_000)
    kind: PromptKind | None = Field(
        None,
        description="Optional override; default is auto-routed from message text.",
    )


@router.post("/chat")
async def local_chat(
    body: LocalChatBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Run routed Ollama model; returns reply + routing metadata."""
    if not _local_ai_enabled():
        raise HTTPException(status_code=503, detail="Local AI disabled (THIRAMAI_LOCAL_AI_ENABLED=0).")
    kind = body.kind or classify_prompt_kind(body.message)
    model = ollama_model_for_kind(kind)
    try:
        reply = await ollama_chat_async(
            model,
            body.message.strip(),
            system=_SYSTEM,
        )
    except OllamaUnavailableError as e:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {e}") from e
    if not reply:
        raise HTTPException(status_code=502, detail="Empty response from Ollama.")
    return {
        "ok": True,
        "reply": reply,
        "model": model,
        "kind": kind.value,
        "routed_by": "override" if body.kind else "heuristic",
    }


@router.post("/chat/sync")
def local_chat_sync(
    body: LocalChatBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Same as POST /chat but sync (for workers); prefer /chat from async clients."""
    if not _local_ai_enabled():
        raise HTTPException(status_code=503, detail="Local AI disabled.")
    kind = body.kind or classify_prompt_kind(body.message)
    model = ollama_model_for_kind(kind)
    try:
        reply = ollama_chat_sync(model, body.message.strip(), system=_SYSTEM)
    except OllamaUnavailableError as e:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {e}") from e
    if not reply:
        raise HTTPException(status_code=502, detail="Empty response from Ollama.")
    return {"ok": True, "reply": reply, "model": model, "kind": kind.value}


@router.post("/chat/stream")
async def local_chat_stream_route(
    body: LocalChatBody,
    _user: CurrentUser = Depends(get_current_user),
):
    """Stream plain text chunks (Ollama token deltas concatenated)."""
    if not _local_ai_enabled():
        raise HTTPException(status_code=503, detail="Local AI disabled.")

    kind = body.kind or classify_prompt_kind(body.message)
    model = ollama_model_for_kind(kind)

    async def gen():
        try:
            async for chunk in ollama_chat_stream(
                model,
                body.message.strip(),
                system=_SYSTEM,
            ):
                yield chunk
        except OllamaUnavailableError as e:
            yield f"\n[error] {e}\n"

    headers = {
        "X-THIRAMAI-Model": model,
        "X-THIRAMAI-Kind": kind.value,
    }
    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8", headers=headers)


@router.get("/router-preview")
async def router_preview(
    q: str,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Debug: which model would run for ``q`` (no Ollama call)."""
    k = classify_prompt_kind(q)
    return {"kind": k.value, "model": ollama_model_for_kind(k)}
