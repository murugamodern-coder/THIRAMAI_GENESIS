"""
Background tick: lightweight org snapshot → one guidance line into the thought stream.

Opt-in via ``THIRAMAI_BACKGROUND_AGENT=1``. Requires ``THIRAMAI_BACKGROUND_USER_ID`` and
``THIRAMAI_BACKGROUND_ORG_ID`` (or agent skips work and logs a hint once).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from core.personal_ai_engine import generate_daily_guidance
from services.personal_os_aggregate import build_personal_today_sync
from services.thought_stream import append_thought

_LOG = logging.getLogger(__name__)

_INTERVAL_SEC = max(15, min(600, int((os.getenv("THIRAMAI_BACKGROUND_AGENT_INTERVAL") or "60").strip() or "60")))

_stop: asyncio.Event | None = None
_task: asyncio.Task[Any] | None = None
_warned_config = False


def background_agent_enabled() -> bool:
    return (os.getenv("THIRAMAI_BACKGROUND_AGENT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _parse_int(name: str) -> int:
    try:
        return int((os.getenv(name) or "0").strip() or "0")
    except ValueError:
        return 0


async def _tick() -> None:
    global _warned_config
    uid = _parse_int("THIRAMAI_BACKGROUND_USER_ID")
    oid = _parse_int("THIRAMAI_BACKGROUND_ORG_ID")
    if uid <= 0 or oid <= 0:
        if not _warned_config:
            _warned_config = True
            append_thought(
                "Background agent: set THIRAMAI_BACKGROUND_USER_ID and THIRAMAI_BACKGROUND_ORG_ID.",
                agent="background_agent",
                phase="config",
            )
        return
    try:
        payload = await asyncio.to_thread(
            build_personal_today_sync,
            user_id=uid,
            organization_id=oid,
            low_stock_threshold=int((os.getenv("THIRAMAI_BACKGROUND_LOW_STOCK") or "5").strip() or "5"),
        )
        tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
        low = payload.get("low_stock") if isinstance(payload.get("low_stock"), dict) else {}
        n_low = int(low.get("count") or 0)
        snap = {
            "tasks": tasks,
            "reminders": payload.get("reminders") or [],
            "low_stock": low,
            "today_sales": payload.get("today_sales") or {},
            "authenticated": True,
            "user_id": uid,
            "organization_id": oid,
            "daily_score": int(payload.get("daily_score") or 0),
            "streak_days": int(payload.get("streak_days") or 0),
        }
        g = await asyncio.to_thread(lambda: generate_daily_guidance(snap, memory=None, followups=None))
        top = (g.get("top_focus") or g.get("focus") or "").strip()
        if not top:
            return
        if len(tasks) < 2 and n_low == 0:
            return
        append_thought(
            f"[auto] {top}",
            agent="background_agent",
            phase="suggest",
            meta={"tasks_open": len(tasks), "low_stock_skus": n_low},
        )
    except Exception as exc:
        _LOG.warning("background_agent tick failed: %s", exc)
        append_thought(
            f"Background agent error: {type(exc).__name__}",
            agent="background_agent",
            phase="error",
        )


async def _loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await _tick()
        except asyncio.CancelledError:
            break
        except Exception:
            _LOG.exception("background_agent loop")
        try:
            await asyncio.wait_for(stop.wait(), timeout=_INTERVAL_SEC)
        except asyncio.TimeoutError:
            continue


def start_background_agent() -> None:
    global _stop, _task
    if not background_agent_enabled():
        return
    if _task and not _task.done():
        return
    loop = asyncio.get_running_loop()
    _stop = asyncio.Event()
    _task = loop.create_task(_loop(_stop))
    append_thought(
        f"Background agent started (every {_INTERVAL_SEC}s).",
        agent="background_agent",
        phase="boot",
    )


def stop_background_agent() -> None:
    global _task, _stop
    if _stop:
        _stop.set()
    if _task:
        _task.cancel()
        _task = None
    _stop = None
