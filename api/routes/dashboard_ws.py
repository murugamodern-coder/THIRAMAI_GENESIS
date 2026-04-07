"""
Real-time Command Center: WebSocket push for SAP-style dashboard payload.

``GET /dashboard/command-center`` remains the canonical HTTP API; this channel mirrors the same
builder on a fixed interval for live UI updates.

Auth: after connect, the client must send **one JSON text message** first:
``{"token": "<JWT access token>"}`` (optional ``"threshold": <int>``). JWTs must not appear in the URL.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from api.dependencies import try_resolve_current_user_from_access_token
from core.safe_errors import safe_errors_enabled
from services.command_center import build_command_center_sap_payload_sync

router = APIRouter(tags=["Realtime"])

_MAX_AUTH_JSON_BYTES = 16_384


def _ws_push_interval_seconds() -> float:
    raw = (os.getenv("THIRAMAI_DASHBOARD_WS_INTERVAL") or "").strip()
    if raw:
        try:
            return min(120.0, max(3.0, float(raw)))
        except ValueError:
            pass
    return 7.0


async def _read_first_auth_message(
    websocket: WebSocket, *, query_threshold: int
) -> tuple[str | None, int]:
    """
    First client message must be JSON: ``{"token": "...", "threshold": optional}``.
    Returns ``(access_token_or_none, threshold)``.
    """
    try:
        raw = await websocket.receive_text()
    except WebSocketDisconnect:
        return None, query_threshold
    if len(raw.encode("utf-8")) > _MAX_AUTH_JSON_BYTES:
        return None, query_threshold
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, query_threshold
    if not isinstance(data, dict):
        return None, query_threshold
    token = (data.get("token") or "").strip()
    thr = query_threshold
    if "threshold" in data and data["threshold"] is not None:
        thr = _threshold_from_ws_query(str(data["threshold"]))
    return (token if token else None), thr


def _threshold_from_ws_query(raw: str | None) -> int:
    default_raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip() or "5"
    try:
        default = max(0, min(10_000, int(default_raw)))
    except ValueError:
        default = 5
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(0, min(10_000, int(str(raw).strip())))
    except ValueError:
        return default


@router.websocket("/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """
    Authenticated stream of command-center snapshots.

    After the socket is accepted, send one JSON text message:
    ``{"token": "<JWT>"}`` (optional ``"threshold"``). Query ``?threshold=`` is still supported;
    do **not** pass ``token`` in the query string (rejected).

    Each server message is JSON with ``type: dashboard_tick`` plus the same keys as the HTTP response
    (``life_dashboard``, ``business_summary``, ``alerts``, ``next_best_move``, legacy fields, …).
    """
    await websocket.accept()
    if (websocket.query_params.get("token") or "").strip():
        await websocket.close(code=1008, reason="Auth token in query string is not supported; send JSON first")
        return

    query_thr = _threshold_from_ws_query(websocket.query_params.get("threshold"))
    token, thr = await _read_first_auth_message(websocket, query_threshold=query_thr)

    user = try_resolve_current_user_from_access_token(token or None)
    if user is None:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    if int(user.id) <= 0:
        await websocket.send_json(
            {
                "type": "error",
                "detail": "Valid user id required",
            }
        )
        await websocket.close(code=1008, reason="Invalid user")
        return

    interval = _ws_push_interval_seconds()

    def _build() -> dict[str, Any]:
        return build_command_center_sap_payload_sync(
            int(user.id),
            int(user.organization_id),
            low_stock_threshold=thr,
        )

    try:
        while True:
            payload = await asyncio.to_thread(_build)
            payload["type"] = "dashboard_tick"
            payload["channel"] = "ws/dashboard"
            await websocket.send_json(jsonable_encoder(payload))
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            if safe_errors_enabled():
                await websocket.send_json({"type": "error", "detail": "internal_error"})
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": type(exc).__name__,
                        "message": str(exc)[:500],
                    }
                )
        except Exception:
            pass
        await websocket.close(code=1011)
