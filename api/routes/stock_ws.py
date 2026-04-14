"""
Upgrade 4 — WebSocket live stock channel: prices, user alerts, risk cap, indicator signals.

Auth: first message must be JSON ``{"token": "<JWT access token>"}`` (same policy as ``/ws/dashboard``).
Path ``user_id`` must match the authenticated user id.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from api.dependencies import try_resolve_current_user_from_access_token
from core.safe_errors import safe_errors_enabled
from services.stock_realtime_monitor import connect_to_market_data, stock_monitor

router = APIRouter(tags=["Realtime Stocks"])

_log = logging.getLogger("thiramai.stock_ws")

_MAX_AUTH_JSON_BYTES = 16_384


async def _read_first_auth_message(websocket: WebSocket) -> str | None:
    try:
        raw = await websocket.receive_text()
    except WebSocketDisconnect:
        return None
    if len(raw.encode("utf-8")) > _MAX_AUTH_JSON_BYTES:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return (data.get("token") or "").strip() or None


@router.websocket("/stocks/{user_id}")
async def websocket_stocks(websocket: WebSocket, user_id: int) -> None:
    await websocket.accept()
    if (websocket.query_params.get("token") or "").strip():
        await websocket.close(code=1008, reason="Auth token in query string is not supported; send JSON first")
        return

    token = await _read_first_auth_message(websocket)
    user = try_resolve_current_user_from_access_token(token)
    if user is None:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    uid = int(user.id)
    if uid <= 0 or uid != int(user_id):
        await websocket.send_json({"type": "error", "detail": "user_id mismatch"})
        await websocket.close(code=1008, reason="Invalid user")
        return

    oid = int(user.organization_id) if int(user.organization_id) > 0 else None
    q: asyncio.Queue = asyncio.Queue(maxsize=8)
    stock_monitor.register_subscriber(uid, q, organization_id=oid)
    await stock_monitor.ensure_poll_task()
    _ = connect_to_market_data()

    async def _drain_client() -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            return
        except Exception:
            return

    drainer = asyncio.create_task(_drain_client())

    try:
        await websocket.send_json(
            {
                "type": "stock_ws_ready",
                "user_id": uid,
                "poll_interval_sec": stock_monitor.poll_interval_sec(),
            }
        )
        while True:
            payload = await q.get()
            await websocket.send_json(jsonable_encoder(payload))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            if safe_errors_enabled():
                await websocket.send_json({"type": "error", "detail": "internal_error"})
            else:
                await websocket.send_json(
                    {"type": "error", "detail": type(exc).__name__, "message": str(exc)[:500]}
                )
        except Exception:
            pass
        await websocket.close(code=1011)
    finally:
        drainer.cancel()
        try:
            await drainer
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        stock_monitor.unregister_subscriber(uid, q)
