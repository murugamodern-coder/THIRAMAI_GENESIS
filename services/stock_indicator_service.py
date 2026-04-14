"""Technical indicators for equity signals (RSI, MACD, EMA, Bollinger)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from services.stock_market_data_service import get_ohlc

_log = logging.getLogger("thiramai.stock_indicator")


def _closes_from_ohlc(ohlc: dict[str, Any]) -> np.ndarray:
    bars = ohlc.get("bars") or []
    out: list[float] = []
    for b in bars:
        c = b.get("close")
        if c is not None:
            try:
                out.append(float(c))
            except Exception:
                continue
    return np.array(out, dtype=float)


def rsi_series(close: np.ndarray, period: int = 14) -> float | None:
    if close is None or len(close) < period + 1:
        return None
    deltas = np.diff(close.astype(float))
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)
    ag = np.convolve(gains, np.ones(period), "valid") / period
    al = np.convolve(losses, np.ones(period), "valid") / period
    if len(ag) == 0 or al[-1] == 0:
        return 100.0 if ag[-1] > 0 else None
    rs = ag[-1] / al[-1]
    return float(100 - (100 / (1 + rs)))


def ema_last(close: np.ndarray, span: int) -> float | None:
    if close is None or len(close) < span:
        return None
    x = close.astype(float)
    alpha = 2.0 / (span + 1)
    v = x[0]
    for i in range(1, len(x)):
        v = alpha * x[i] + (1 - alpha) * v
    return float(v)


def macd_components(close: np.ndarray) -> tuple[float | None, float | None, float | None]:
    """Return (macd_line, signal_line, histogram) at last bar using recursive EMA style."""
    if close is None or len(close) < 35:
        return None, None, None
    x = close.astype(float)
    a12, a26, a9 = 2 / 13, 2 / 27, 2 / 10
    e12 = e26 = x[0]
    macd_line: list[float] = []
    for px in x:
        e12 = a12 * px + (1 - a12) * e12
        e26 = a26 * px + (1 - a26) * e26
        macd_line.append(e12 - e26)
    m = np.array(macd_line, dtype=float)
    sig = m[0]
    for v in m[1:]:
        sig = a9 * v + (1 - a9) * sig
    macd_v = float(m[-1])
    sig_v = float(sig)
    return macd_v, sig_v, macd_v - sig_v


def bollinger_position(close: np.ndarray, window: int = 20, num_std: float = 2.0) -> dict[str, Any]:
    if close is None or len(close) < window:
        return {"position": "unknown", "pct_b": None, "middle": None, "upper": None, "lower": None}
    tail = close[-window:].astype(float)
    mid = float(np.mean(tail))
    sd = float(np.std(tail))
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    last = float(close[-1])
    if upper == lower:
        pct_b = 0.5
    else:
        pct_b = (last - lower) / (upper - lower)
    pos = "below_lower" if last < lower else "above_upper" if last > upper else "inside"
    return {"position": pos, "pct_b": round(pct_b, 3), "middle": mid, "upper": upper, "lower": lower}


def analyze_indicators(symbol: str, *, interval: str = "1d", exchange_suffix: str = "NS") -> dict[str, Any]:
    ohlc = get_ohlc(symbol, interval=interval, exchange_suffix=exchange_suffix)
    if not ohlc.get("ok"):
        return {"ok": False, "error": ohlc.get("error") or "ohlc failed"}
    close = _closes_from_ohlc(ohlc)
    if len(close) < 10:
        return {"ok": False, "error": "insufficient closes"}
    rsi = rsi_series(close, 14)
    macd_v, sig_v, hist = macd_components(close)
    ema9 = ema_last(close, 9)
    ema21 = ema_last(close, 21)
    bb = bollinger_position(close, 20, 2.0)
    trend = "neutral"
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21 and close[-1] >= ema9:
            trend = "bullish"
        elif ema9 < ema21 and close[-1] <= ema9:
            trend = "bearish"
    ema_signal = "bullish_cross" if ema9 and ema21 and ema9 > ema21 else "bearish_cross" if ema9 and ema21 and ema9 < ema21 else "flat"
    return {
        "ok": True,
        "symbol": (symbol or "").strip().upper(),
        "interval": interval,
        "last_close": round(float(close[-1]), 4),
        "rsi": None if rsi is None else round(rsi, 2),
        "macd": None if macd_v is None else round(macd_v, 4),
        "macd_signal": None if sig_v is None else round(sig_v, 4),
        "macd_histogram": None if hist is None else round(hist, 4),
        "ema9": None if ema9 is None else round(ema9, 4),
        "ema21": None if ema21 is None else round(ema21, 4),
        "ema_signal": ema_signal,
        "bollinger": bb,
        "trend": trend,
    }
