"""ATR-based position sizing for risk-adjusted entries."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def calculate_atr(candles: list[dict], period: int = 14) -> float:
    """Average True Range over the last ``period`` candles."""
    if len(candles) < period + 1:
        return 0.0
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    return sum(true_ranges[-period:]) / period


def calculate_position_size(
    capital: float,
    current_price: float,
    candles: list[dict],
    risk_per_trade_pct: float = 0.01,
    atr_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Quantity sized so a stop at ``ATR * atr_multiplier`` risks ``risk_per_trade_pct`` of capital.

    Falls back to a fixed 10% capital allocation when ATR cannot be computed (e.g. empty candles).
    """
    if current_price <= 0:
        return {"quantity": 0, "method": "invalid_price"}

    atr = calculate_atr(candles)

    if atr == 0:
        qty = max(1, int(capital * 0.10 / current_price))
        return {
            "quantity": qty,
            "stop_loss": round(current_price * 0.97, 2),
            "target": round(current_price * 1.025, 2),
            "risk_amount": round(capital * 0.01, 2),
            "atr": 0.0,
            "method": "fallback",
        }

    risk_amount = capital * risk_per_trade_pct
    stop_distance = atr * atr_multiplier
    stop_loss = current_price - stop_distance
    target = current_price + (stop_distance * 1.5)  # 1.5:1 reward/risk

    qty = max(1, int(risk_amount / stop_distance))
    max_qty = max(1, int(capital * 0.20 / current_price))
    qty = min(qty, max_qty)

    return {
        "quantity": qty,
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "risk_amount": round(risk_amount, 2),
        "atr": round(atr, 2),
        "atr_multiplier": atr_multiplier,
        "method": "atr_based",
    }
