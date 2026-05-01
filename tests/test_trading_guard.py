"""Tests for :mod:`services.broker.trading_guard`.

External dependencies (DB vault, Redis, portfolio_service) are mocked using
context managers.  Patch targets are the submodule paths since all imports
happen inside the guard functions (lazy imports).
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from services.broker.trading_guard import (
    _kill_switch_redis_key,
    _seconds_until_ist_midnight,
    agent_trade_precheck,
    enforce_daily_loss_kill_switch,
    is_agent_trade_kill_active,
    should_trigger_daily_loss_kill,
)

# portfolio_service functions are top-level imports in trading_guard.py,
# so they must be patched via the trading_guard module namespace.
_PNL = "services.broker.trading_guard.daily_equity_pnl_inr_sync"
_LIMIT = "services.broker.trading_guard.trading_guard_limit_inr"
_LIQUIDATE = "services.broker.trading_guard.liquidate_all_equity_positions_sync"

# vault / redis functions are lazy imports (inside each function body),
# so they must be patched at their source modules.
_VAULT_HALTED = "services.security.vault_service.is_trading_halted"
_VAULT_SET = "services.security.vault_service.set_trading_halted_for_ist_session"
_REDIS_CLIENT = "services.worker_heartbeat.redis_client"


# ---------------------------------------------------------------------------
# _seconds_until_ist_midnight
# ---------------------------------------------------------------------------


def test_seconds_until_ist_midnight_positive():
    secs = _seconds_until_ist_midnight()
    assert secs >= 60
    assert secs <= 86400


# ---------------------------------------------------------------------------
# _kill_switch_redis_key format
# ---------------------------------------------------------------------------


def test_kill_switch_redis_key_format():
    key = _kill_switch_redis_key(42)
    assert key.startswith("thiramai:agent_trade_kill:42:")
    date_part = key.split(":")[-1]
    assert len(date_part) == 10
    assert "-" in date_part


def test_kill_switch_redis_key_different_users():
    k1 = _kill_switch_redis_key(1)
    k2 = _kill_switch_redis_key(2)
    assert k1 != k2


# ---------------------------------------------------------------------------
# is_agent_trade_kill_active — validation
# ---------------------------------------------------------------------------


def test_invalid_user_id_zero_not_active():
    assert is_agent_trade_kill_active(0) is False


def test_invalid_user_id_negative_not_active():
    assert is_agent_trade_kill_active(-1) is False


def test_db_halt_active_returns_true():
    with patch(_VAULT_HALTED, return_value=True):
        assert is_agent_trade_kill_active(1) is True


def test_db_halt_false_redis_active_returns_true():
    r = MagicMock()
    r.get.return_value = b"1"
    with patch(_VAULT_HALTED, return_value=False), \
         patch(_REDIS_CLIENT, return_value=r):
        assert is_agent_trade_kill_active(1) is True


def test_no_halt_active_returns_false():
    r = MagicMock()
    r.get.return_value = None
    with patch(_VAULT_HALTED, return_value=False), \
         patch(_REDIS_CLIENT, return_value=r):
        assert is_agent_trade_kill_active(1) is False


def test_db_exception_falls_back_to_redis():
    r = MagicMock()
    r.get.return_value = None
    with patch(_VAULT_HALTED, side_effect=Exception("db_down")), \
         patch(_REDIS_CLIENT, return_value=r):
        result = is_agent_trade_kill_active(1)
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# should_trigger_daily_loss_kill
# ---------------------------------------------------------------------------


def test_invalid_user_no_trigger():
    assert should_trigger_daily_loss_kill(0) is False


def test_loss_below_limit_no_trigger():
    with patch(_LIMIT, return_value=5000.0), \
         patch(_PNL, return_value=-3000.0):
        assert should_trigger_daily_loss_kill(1) is False


def test_loss_exceeds_limit_triggers():
    with patch(_LIMIT, return_value=5000.0), \
         patch(_PNL, return_value=-5001.0):
        assert should_trigger_daily_loss_kill(1) is True


def test_loss_exactly_at_limit_triggers():
    with patch(_LIMIT, return_value=5000.0), \
         patch(_PNL, return_value=-5000.0):
        assert should_trigger_daily_loss_kill(1) is True


def test_no_loss_no_trigger():
    with patch(_LIMIT, return_value=5000.0), \
         patch(_PNL, return_value=0.0):
        assert should_trigger_daily_loss_kill(1) is False


# ---------------------------------------------------------------------------
# enforce_daily_loss_kill_switch — idempotency
# ---------------------------------------------------------------------------


def test_invalid_user_returns_error():
    result = enforce_daily_loss_kill_switch(0)
    assert result["ok"] is False
    assert "invalid" in result.get("error", "").lower()


def test_already_blocked_returns_early():
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=True):
        result = enforce_daily_loss_kill_switch(1)
    assert result["ok"] is True
    assert result.get("already_blocked") is True


def test_no_trigger_returns_not_triggered():
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=False), \
         patch("services.broker.trading_guard.should_trigger_daily_loss_kill", return_value=False):
        result = enforce_daily_loss_kill_switch(1)
    assert result["ok"] is True
    assert result.get("triggered") is False


def test_trigger_liquidates_and_sets_redis():
    liq_result = {"ok": True, "positions_liquidated": 3}
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=False), \
         patch("services.broker.trading_guard.should_trigger_daily_loss_kill", return_value=True), \
         patch(_LIQUIDATE, return_value=liq_result) as mock_liq, \
         patch("services.broker.trading_guard._redis_set_kill") as mock_redis, \
         patch(_VAULT_SET) as mock_vault:
        result = enforce_daily_loss_kill_switch(1)
    assert result["ok"] is True
    assert result["triggered"] is True
    assert result["liquidation"]["ok"] is True
    mock_liq.assert_called_once_with(1)
    mock_redis.assert_called_once_with(1)
    mock_vault.assert_called_once_with(1)


def test_db_persist_failure_still_returns_triggered():
    """Even when vault DB persist fails, triggered=True and liquidation ran."""
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=False), \
         patch("services.broker.trading_guard.should_trigger_daily_loss_kill", return_value=True), \
         patch(_LIQUIDATE, return_value={"ok": True, "positions_liquidated": 0}), \
         patch("services.broker.trading_guard._redis_set_kill"), \
         patch(_VAULT_SET, side_effect=Exception("db_error")):
        result = enforce_daily_loss_kill_switch(1)
    assert result["ok"] is True
    assert result["triggered"] is True


def test_broker_api_failure_propagates():
    """Broker API failure should propagate rather than silently swallow."""
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=False), \
         patch("services.broker.trading_guard.should_trigger_daily_loss_kill", return_value=True), \
         patch(_LIQUIDATE, side_effect=Exception("broker_api_down")), \
         patch("services.broker.trading_guard._redis_set_kill"), \
         patch(_VAULT_SET):
        with pytest.raises(Exception, match="broker_api_down"):
            enforce_daily_loss_kill_switch(1)


# ---------------------------------------------------------------------------
# agent_trade_precheck
# ---------------------------------------------------------------------------


def test_agent_trade_precheck_invalid_user():
    allowed, msg = agent_trade_precheck(0)
    assert allowed is False
    assert msg is not None


def test_agent_trade_precheck_blocked():
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=True):
        allowed, msg = agent_trade_precheck(1)
    assert allowed is False
    assert msg is not None and len(msg) > 0


def test_agent_trade_precheck_allowed():
    with patch("services.broker.trading_guard.is_agent_trade_kill_active", return_value=False), \
         patch("services.broker.trading_guard.should_trigger_daily_loss_kill", return_value=False), \
         patch("services.broker.trading_guard.enforce_daily_loss_kill_switch",
               return_value={"ok": True, "triggered": False}):
        allowed, msg = agent_trade_precheck(1)
    assert allowed is True
    assert msg is None


# ---------------------------------------------------------------------------
# Concurrent halt requests
# ---------------------------------------------------------------------------


def test_concurrent_precheck_no_race():
    """Concurrent agent_trade_precheck calls must not raise."""
    errors: list[str] = []

    def call():
        try:
            with patch("services.broker.trading_guard.is_agent_trade_kill_active",
                       return_value=False), \
                 patch("services.broker.trading_guard.should_trigger_daily_loss_kill",
                       return_value=False), \
                 patch("services.broker.trading_guard.enforce_daily_loss_kill_switch",
                       return_value={"ok": True, "triggered": False}):
                agent_trade_precheck(1)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent precheck raised: {errors}"
