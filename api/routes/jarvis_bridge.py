"""
JARVIS UI bridge: machine-readable feeds for the live ops dashboard (thought stream, etc.).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.thought_stream import read_thought_stream

router = APIRouter(prefix="/logs", tags=["JARVIS UI"])


@router.get(
    "/thought_stream.json",
    summary="Orchestrator thought stream (JSON)",
    description="Append-only reasoning lines written by ``core.orchestrator`` and workers; polled by ``/dashboard/live``.",
)
def get_thought_stream_json() -> JSONResponse:
    return JSONResponse(content=read_thought_stream())
