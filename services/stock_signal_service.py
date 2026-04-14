"""Rule-based intraday / swing-style signals (not investment advice)."""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

from services.stock_indicator_service import analyze_indicators
from services.stock_market_data_service import get_live_price

_log = logging.getLogger("thiramai.stock_signal")


def _max_daily_loss_inr() -> Decimal:
    try:
        return Decimal(str((os.getenv("THIRAMAI_MAX_DAILY_LOSS_INR") or "2000").strip()))
    except Exception:
        return Decimal("2000")


def generate_intraday_signal(
    symbol: str,
    *,
    user_id: int | None = None,
    exchange_suffix: str = "NS",
) -> dict[str, Any]:
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "symbol required"}

    if user_id and int(user_id) > 0:
        try:
            from services.portfolio_service import daily_equity_pnl_inr_sync, is_equity_risk_blocked_sync

            if is_equity_risk_blocked_sync(int(user_id)):
                return {
                    "ok": True,
                    "action": "HOLD",
                    "entry_price": None,
                    "target_price": None,
                    "stop_loss": None,
                    "risk_reward": None,
                    "reasoning": "Daily equity loss limit reached — signals disabled until next session.",
                    "risk_blocked": True,
                }
            pnl = daily_equity_pnl_inr_sync(int(user_id))
            if pnl <= -_max_daily_loss_inr():
                try:
                    from services.portfolio_service import enforce_equity_risk_block_if_needed_sync

                    enforce_equity_risk_block_if_needed_sync(int(user_id))
                except Exception:
                    pass
                return {
                    "ok": True,
                    "action": "HOLD",
                    "entry_price": None,
                    "target_price": None,
                    "stop_loss": None,
                    "risk_reward": None,
                    "reasoning": f"Realized P&L today ({pnl} INR) exceeds max daily loss limit.",
                    "risk_blocked": True,
                }
        except Exception as exc:
            _log.debug("risk check skipped: %s", exc)

    ind = analyze_indicators(sym, interval="1d", exchange_suffix=exchange_suffix)
    if not ind.get("ok"):
        return {"ok": False, "error": ind.get("error") or "indicators failed"}
    px = get_live_price(sym, exchange_suffix=exchange_suffix)
    last = float(px["last"]) if px.get("ok") else float(ind["last_close"])
    rsi = ind.get("rsi")
    macd = ind.get("macd")
    sig = ind.get("macd_signal")
    ema9 = ind.get("ema9")
    ema21 = ind.get("ema21")
    hist = ind.get("macd_histogram")

    action = "HOLD"
    reasoning_parts: list[str] = []
    target = last * 1.015
    stop = last * 0.985
    rr = 1.2

    if rsi is not None:
        reasoning_parts.append(f"RSI(14)={rsi}")
        if rsi < 30:
            action = "BUY"
            reasoning_parts.append("RSI oversold zone")
            target = last * 1.025
            stop = last * 0.97
        elif rsi > 70:
            action = "SELL"
            reasoning_parts.append("RSI overbought zone")
            target = last * 0.975
            stop = last * 1.02

    if macd is not None and sig is not None and hist is not None:
        reasoning_parts.append(f"MACD hist={hist:.4f}")
        if action == "HOLD" and macd > sig and hist > 0:
            action = "BUY"
            reasoning_parts.append("MACD bullish crossover / momentum")
            target = last * 1.02
            stop = last * 0.98
        elif action == "HOLD" and macd < sig and hist < 0:
            action = "SELL"
            reasoning_parts.append("MACD bearish crossover")
            target = last * 0.98
            stop = last * 1.015

    if ema9 and ema21:
        reasoning_parts.append(f"EMA9/21={ema9}/{ema21} ({ind.get('ema_signal')})")
        if action == "HOLD" and ema9 > ema21 and rsi and 40 < rsi < 60:
            action = "BUY"
            reasoning_parts.append("EMA stack bullish mid-band")
            target = last * 1.018
            stop = last * 0.982

    risk = abs(last - stop) if last and stop else 0.01
    reward = abs(target - last) if target else 0.01
    if risk > 0:
        rr = round(float(reward / risk), 2)

    return {
        "ok": True,
        "symbol": sym,
        "action": action,
        "entry_price": round(last, 4),
        "target_price": round(float(target), 4),
        "stop_loss": round(float(stop), 4),
        "risk_reward": rr,
        "reasoning": "; ".join(reasoning_parts) if reasoning_parts else "No strong alignment — hold.",
        "indicators": {k: ind[k] for k in ("rsi", "macd", "macd_signal", "trend", "ema_signal") if k in ind},
        "disclaimer": (os.getenv("THIRAMAI_MARKET_DISCLAIMER") or "Not investment advice."),
    }
