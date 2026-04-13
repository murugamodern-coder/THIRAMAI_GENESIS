"""YFinance + light technicals for Jarvis stock tools (NSE .NS)."""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

_log = logging.getLogger("thiramai.stock_market_jarvis")


def _symbol_yf(symbol: str, exchange_suffix: str = "NS") -> str:
    s = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    suf = (exchange_suffix or "NS").strip().upper()
    return f"{s}.{suf}" if suf else s


def _rsi(series: np.ndarray, period: int = 14) -> float | None:
    if series is None or len(series) < period + 1:
        return None
    deltas = np.diff(series.astype(float))
    if len(deltas) < period:
        return None
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)
    ag = np.convolve(gains, np.ones(period), "valid") / period
    al = np.convolve(losses, np.ones(period), "valid") / period
    if al[-1] == 0:
        return 100.0
    rs = ag[-1] / al[-1]
    return float(100 - (100 / (1 + rs)))


def _ema(arr: np.ndarray, span: int) -> float | None:
    if arr is None or len(arr) < span:
        return None
    x = arr.astype(float)
    alpha = 2.0 / (span + 1)
    v = x[0]
    for i in range(1, len(x)):
        v = alpha * x[i] + (1 - alpha) * v
    return float(v)


def _macd(close: np.ndarray) -> tuple[float | None, float | None]:
    if close is None or len(close) < 35:
        return None, None
    x = close.astype(float)
    ema12 = x[0]
    ema26 = x[0]
    a12, a26 = 2 / 13, 2 / 27
    macd_line: list[float] = []
    for px in x:
        ema12 = a12 * px + (1 - a12) * ema12
        ema26 = a26 * px + (1 - a26) * ema26
        macd_line.append(ema12 - ema26)
    m = np.array(macd_line, dtype=float)
    if len(m) < 9:
        return None, None
    signal = m[0]
    a9 = 2 / 10
    for v in m[1:]:
        signal = a9 * v + (1 - a9) * signal
    return float(m[-1]), float(signal)


def analyze_symbol_sync(
    *,
    symbol: str,
    timeframe: str = "intraday",
    exchange_suffix: str = "NS",
) -> dict[str, Any]:
    """
    Returns signal + levels. Uses daily bars if intraday history is thin (yfinance quirk).
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}

    sym = _symbol_yf(symbol, exchange_suffix)
    try:
        # Prefer hourly for swing; 5m often empty for Indian names
        interval = "1h" if (timeframe or "").lower() == "swing" else "1d"
        period = "3mo" if interval == "1d" else "5d"
        df = yf.download(sym, period=period, interval=interval, progress=False, threads=False)
    except Exception as exc:
        _log.warning("yfinance download failed %s: %s", sym, exc)
        return {"ok": False, "error": str(exc)}

    if df is None or df.empty or "Close" not in df.columns:
        return {"ok": False, "error": f"no data for {sym}"}

    close = df["Close"].dropna().values
    if len(close) < 5:
        return {"ok": False, "error": "insufficient price history"}

    last = float(close[-1])
    rsi = _rsi(close, 14)
    macd_v, sig_v = _macd(close)
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)

    signal = "HOLD"
    reason_parts: list[str] = []
    target = last * 1.015
    stop = last * 0.99
    rr = 1.5

    if rsi is not None:
        reason_parts.append(f"RSI(14)≈{rsi:.1f}")
    if macd_v is not None and sig_v is not None:
        reason_parts.append(f"MACD vs signal: {macd_v:.3f} / {sig_v:.3f}")

    if rsi is not None and macd_v is not None and sig_v is not None and ema9 is not None and ema21 is not None:
        if rsi < 42 and macd_v > sig_v and ema9 > ema21:
            signal = "BUY"
            target = last * 1.02
            stop = last * 0.985
        elif rsi > 68 and macd_v < sig_v:
            signal = "SELL"
            target = last * 0.98
            stop = last * 1.01

    risk = abs(last - stop) if last and stop else 0.01
    reward = abs(target - last) if target else 0.01
    if risk > 0:
        rr = round(reward / risk, 2)

    return {
        "ok": True,
        "symbol": sym,
        "timeframe": timeframe,
        "signal": signal,
        "current_price": round(last, 2),
        "entry_price": round(last, 2),
        "target": round(float(target), 2),
        "stop_loss": round(float(stop), 2),
        "risk_reward_ratio": rr,
        "rsi": None if rsi is None else round(rsi, 2),
        "reason": "; ".join(reason_parts) if reason_parts else "Neutral momentum — wait for clearer alignment.",
    }


def get_index_snapshot_sync(ticker: str = "^NSEI") -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}
    t = (ticker or "^NSEI").strip()
    try:
        df = yf.download(t, period="5d", interval="1d", progress=False, threads=False)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if df is None or df.empty or "Close" not in df.columns:
        return {"ok": False, "error": "no index data"}
    close = df["Close"].dropna()
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    chg = ((last - prev) / prev * 100) if prev else 0.0
    return {"ok": True, "ticker": t, "last": round(last, 2), "change_pct": round(chg, 2)}


def morning_market_brief_sync(*, watchlist_symbols: list[str]) -> dict[str, Any]:
    nifty = get_index_snapshot_sync("^NSEI")
    sensex = get_index_snapshot_sync("^BSESN")
    signals: list[dict[str, Any]] = []
    for raw in (watchlist_symbols or [])[:12]:
        s = str(raw).strip().upper()
        if not s:
            continue
        sig = analyze_symbol_sync(symbol=s, timeframe="swing")
        if sig.get("ok"):
            signals.append(sig)
    signals.sort(key=lambda x: 0 if x.get("signal") == "BUY" else 1 if x.get("signal") == "HOLD" else 2)
    top = signals[0] if signals else None
    return {
        "ok": True,
        "nifty": nifty,
        "sensex": sensex,
        "watchlist_signals": signals[:5],
        "top_signal": top,
        "hint": "Ask Jarvis: analyze stock opportunity for SYMBOL (NSE).",
        "data_source": "yfinance",
        "disclaimer": os.getenv("THIRAMAI_MARKET_DISCLAIMER")
        or "Not investment advice; verify prices with your broker.",
    }
