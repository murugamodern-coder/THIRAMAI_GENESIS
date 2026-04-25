"""
JARVIS UI bridge: machine-readable feeds for the live ops dashboard (thought stream, etc.).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.dependencies import CurrentUser, get_current_user_optional
from services.thought_stream import read_thought_stream

router = APIRouter(prefix="/logs", tags=["JARVIS UI"])


@router.get(
    "/thought_stream.json",
    summary="Orchestrator thought stream (JSON)",
    description="Append-only reasoning lines written by ``core.orchestrator`` and workers; polled by ``/dashboard/live``.",
)
def get_thought_stream_json(_user: CurrentUser | None = Depends(get_current_user_optional)) -> JSONResponse:
    return JSONResponse(content=read_thought_stream())
