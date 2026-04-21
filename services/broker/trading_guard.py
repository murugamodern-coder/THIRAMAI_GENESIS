"""
Daily loss kill-switch for agent / broker execution (IST session).

Uses ``THIRAMAI_MAX_DAILY_LOSS_INR`` (aligned with equity risk guard).
When realized P&amp;L today crosses -limit: liquidate paper holdings and block agent trade steps until IST midnight.
"""

from __future__ import annotations

import logging
from datetime import datetime as dt
from datetime import timedelta
from typing import Any

from zoneinfo import ZoneInfo

from services.portfolio_service import (
    daily_equity_pnl_inr_sync,
    liquidate_all_equity_positions_sync,
    trading_guard_limit_inr,
)

_log = logging.getLogger("thiramai.trading_guard")

_IST = ZoneInfo("Asia/Kolkata")


def _seconds_until_ist_midnight() -> int:
    now = dt.now(_IST)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    sec = int((nxt - now).total_seconds())
    return max(60, min(sec, 86400))


def _kill_switch_redis_key(user_id: int) -> str:
    d = dt.now(_IST).date().isoformat()
    return f"thiramai:agent_trade_kill:{int(user_id)}:{d}"


def _redis_set_kill(user_id: int) -> None:
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if not r:
            return
        r.setex(_kill_switch_redis_key(user_id), _seconds_until_ist_midnight(), "1")
    except Exception as exc:
        _log.debug("redis agent kill: %s", exc)


def _redis_kill_active(user_id: int) -> bool:
    uid = int(user_id)
    if uid <= 0:
        return False
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r and r.get(_kill_switch_redis_key(uid)):
            return True
    except Exception as exc:
        _log.debug("redis kill read: %s", exc)
    return False


def is_agent_trade_kill_active(user_id: int) -> bool:
    """True when trading is halted (PostgreSQL first, then legacy Redis key)."""
    uid = int(user_id)
    if uid <= 0:
        return False
    try:
        from services.security.vault_service import is_trading_halted

        if is_trading_halted(uid):
            return True
    except Exception as exc:
        _log.debug("db trading halt read: %s", exc)
    return _redis_kill_active(uid)


def should_trigger_daily_loss_kill(user_id: int) -> bool:
    uid = int(user_id)
    if uid <= 0:
        return False
    lim = trading_guard_limit_inr()
    pnl = daily_equity_pnl_inr_sync(uid)
    return pnl <= -lim


def enforce_daily_loss_kill_switch(user_id: int) -> dict[str, Any]:
    """
    If today's realized loss exceeds configured max: flatten portfolio + persist halt in PostgreSQL
    (and Redis for backward compatibility).
    Safe to call repeatedly (idempotent once halt is active).
    """
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "invalid user"}
    if is_agent_trade_kill_active(uid):
        return {"ok": True, "already_blocked": True}
    if not should_trigger_daily_loss_kill(uid):
        return {"ok": True, "triggered": False}

    _log.warning("daily loss kill-switch for user_id=%s — liquidating positions", uid)
    liq = liquidate_all_equity_positions_sync(uid)
    _redis_set_kill(uid)
    try:
        from services.security.vault_service import set_trading_halted_for_ist_session

        set_trading_halted_for_ist_session(uid)
    except Exception as exc:
        _log.error("failed to persist trading halt to DB user_id=%s: %s", uid, exc)
    return {"ok": True, "triggered": True, "liquidation": liq}


_MSG_DISABLED = (
    "Trading disabled until next IST session — daily loss limit breached "
    "(positions were flattened)."
)


def agent_trade_precheck(user_id: int) -> tuple[bool, str | None]:
    """Returns (allowed, error_message). DB halt is checked first; survives Redis/process restarts."""
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user for execution"
    if is_agent_trade_kill_active(uid):
        return False, _MSG_DISABLED
    enforce_daily_loss_kill_switch(uid)
    if is_agent_trade_kill_active(uid):
        return False, _MSG_DISABLED
    if should_trigger_daily_loss_kill(uid):
        return False, _MSG_DISABLED
    return True, None
