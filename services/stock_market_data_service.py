"""Live market data (yfinance) with Redis-backed short TTL cache."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

_log = logging.getLogger("thiramai.stock_market_data")

_CACHE_FALLBACK: dict[str, tuple[float, str]] = {}
_DEFAULT_TTL = max(15, min(int((os.getenv("THIRAMAI_STOCK_QUOTE_CACHE_SEC") or "60").strip()), 600))


def _nsepython_last_price(symbol_with_suffix: str) -> float | None:
    """Best-effort NSE cash quote when yfinance is empty or errors (optional ``nsepython``)."""
    raw = (symbol_with_suffix or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not raw:
        return None
    try:
        from nsepython import nse_eq  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        row = nse_eq(raw)
    except Exception:
        return None
    if not isinstance(row, dict):
        return None
    for k in ("lastPrice", "lastprice", "ltp", "close"):
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _yf_symbol(symbol: str, exchange_suffix: str = "NS") -> str:
    s = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    suf = (exchange_suffix or "NS").strip().upper()
    return f"{s}.{suf}" if suf else s


def _cache_get(key: str) -> dict[str, Any] | None:
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
    except Exception as exc:
        _log.debug("redis cache get: %s", exc)
    now = time.monotonic()
    hit = _CACHE_FALLBACK.get(key)
    if hit and now - hit[0] < _DEFAULT_TTL:
        try:
            return json.loads(hit[1])
        except Exception:
            return None
    return None


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    blob = json.dumps(payload, default=str)
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r:
            r.setex(key, _DEFAULT_TTL, blob)
            return
    except Exception as exc:
        _log.debug("redis cache set: %s", exc)
    _CACHE_FALLBACK[key] = (time.monotonic(), blob)


def get_live_price(symbol: str, *, exchange_suffix: str = "NS") -> dict[str, Any]:
    sym = _yf_symbol(symbol, exchange_suffix)
    key = f"thiramai:stock:price:{sym}"
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}
    try:
        t = yf.Ticker(sym)
        info = t.fast_info or {}
        last = getattr(info, "last_price", None) if not isinstance(info, dict) else info.get("last_price")
        if last is None:
            df = yf.download(sym, period="5d", interval="1d", progress=False, threads=False)
            if df is not None and not df.empty and "Close" in df.columns:
                last = float(df["Close"].dropna().iloc[-1])
        if last is None and (exchange_suffix or "NS").strip().upper() in ("NS", "NSE", ""):
            nlp = _nsepython_last_price(sym)
            if nlp is not None:
                last = nlp
        if last is None:
            return {"ok": False, "error": f"no price for {sym}"}
        out = {"ok": True, "symbol": sym, "last": round(float(last), 4), "currency": "INR"}
        _cache_set(key, out)
        return {**out, "cached": False}
    except Exception as exc:
        _log.warning("get_live_price %s: %s", sym, exc)
        if (exchange_suffix or "NS").strip().upper() in ("NS", "NSE", ""):
            nlp = _nsepython_last_price(sym)
            if nlp is not None:
                out = {"ok": True, "symbol": sym, "last": round(float(nlp), 4), "currency": "INR"}
                _cache_set(key, {k: v for k, v in out.items()})
                return {**out, "cached": False, "source": "nsepython"}
        return {"ok": False, "error": str(exc)}


def get_ohlc(symbol: str, *, interval: str = "5m", exchange_suffix: str = "NS") -> dict[str, Any]:
    sym = _yf_symbol(symbol, exchange_suffix)
    iv = (interval or "5m").strip().lower()
    key = f"thiramai:stock:ohlc:{sym}:{iv}"
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}
    period = "5d" if iv in ("1m", "2m", "5m", "15m", "30m", "60m", "1h") else "3mo"
    try:
        df = yf.download(sym, period=period, interval=iv, progress=False, threads=False)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if df is None or df.empty:
        if iv != "1d":
            return get_ohlc(symbol, interval="1d", exchange_suffix=exchange_suffix)
        return {"ok": False, "error": "no ohlc"}
    df2 = df.copy()
    try:
        import pandas as pd

        if isinstance(df2.columns, pd.MultiIndex):
            df2.columns = df2.columns.get_level_values(0)
    except Exception:
        pass
    df2 = df2.tail(120)
    rows: list[dict[str, Any]] = []
    for idx, r in df2.iterrows():
        ts_s = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
        def _f(col: str) -> float | None:
            if col not in df2.columns:
                return None
            try:
                return float(r[col])
            except Exception:
                return None

        rows.append(
            {
                "time": ts_s,
                "open": _f("Open"),
                "high": _f("High"),
                "low": _f("Low"),
                "close": _f("Close"),
            }
        )
    out = {"ok": True, "symbol": sym, "interval": iv, "bars": rows}
    _cache_set(key, out)
    return {**out, "cached": False}


def get_volume(symbol: str, *, exchange_suffix: str = "NS") -> dict[str, Any]:
    sym = _yf_symbol(symbol, exchange_suffix)
    key = f"thiramai:stock:vol:{sym}"
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}
    try:
        df = yf.download(sym, period="10d", interval="1d", progress=False, threads=False)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if df is None or df.empty or "Volume" not in df.columns:
        return {"ok": False, "error": "no volume"}
    v = float(df["Volume"].dropna().iloc[-1])
    out = {"ok": True, "symbol": sym, "volume": int(v), "as_of": str(df.index[-1])}
    _cache_set(key, out)
    return {**out, "cached": False}


def get_52_week(symbol: str, *, exchange_suffix: str = "NS") -> dict[str, Any]:
    sym = _yf_symbol(symbol, exchange_suffix)
    key = f"thiramai:stock:52w:{sym}"
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}
    try:
        import yfinance as yf
    except ImportError:
        return {"ok": False, "error": "yfinance not installed"}
    try:
        t = yf.Ticker(sym)
        info = t.info if hasattr(t, "info") else {}
        hi = info.get("fiftyTwoWeekHigh") or info.get("52WeekHigh")
        lo = info.get("fiftyTwoWeekLow") or info.get("52WeekLow")
        if hi is None or lo is None:
            df = yf.download(sym, period="14mo", interval="1wk", progress=False, threads=False)
            if df is not None and not df.empty and "High" in df.columns:
                hi = float(df["High"].max())
                lo = float(df["Low"].min())
        if hi is None or lo is None:
            return {"ok": False, "error": "no 52w data"}
        out = {
            "ok": True,
            "symbol": sym,
            "high_52w": round(float(hi), 4),
            "low_52w": round(float(lo), 4),
        }
        _cache_set(key, out)
        return {**out, "cached": False}
    except Exception as exc:
        _log.warning("get_52_week %s: %s", sym, exc)
        return {"ok": False, "error": str(exc)}
