"""OHLCV historical data store.

Fetches and stores candlestick data from Kite (preferred when ``KITE_API_KEY`` +
``KITE_ACCESS_TOKEN`` are configured) and falls back to Yahoo Finance via the
``yfinance`` SDK so the backtester always has data to work with.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from core.database import get_engine

logger = logging.getLogger(__name__)


def _kite_credentials_present() -> bool:
    return bool((os.getenv("KITE_API_KEY") or "").strip()) and bool(
        (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
    )


def _fetch_kite(
    symbol: str,
    interval: str,
    days_back: int,
    org_id: int,
) -> dict[str, Any]:
    """Kite historical-data path. Returns ``{"ok": False, ...}`` on any failure."""
    try:
        from services.broker.zerodha_adapter import get_kite_client

        kite = get_kite_client()
        if kite is None:
            return {"ok": False, "error": "kite_not_configured", "symbol": symbol}

        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)

        token = None
        try:
            instruments = kite.instruments("NSE")
            for inst in instruments or []:
                if inst.get("tradingsymbol") == symbol:
                    token = inst.get("instrument_token")
                    break
        except Exception as exc:
            logger.warning("ohlcv_instruments_lookup_failed symbol=%s error=%s", symbol, exc)

        if not token:
            logger.warning("ohlcv_symbol_not_found_in_kite symbol=%s", symbol)
            return {"ok": False, "error": "symbol_not_found", "symbol": symbol}

        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

        engine = get_engine()
        if engine is None:
            return {"ok": False, "error": "database_unavailable", "symbol": symbol}

        stored = 0
        with engine.connect() as conn:
            for candle in data or []:
                conn.execute(
                    text(
                        """
                        INSERT INTO ohlcv_data
                        (symbol, interval, timestamp, open, high, low, close, volume, org_id)
                        VALUES (:symbol, :interval, :ts, :o, :h, :l, :c, :v, :org_id)
                        ON CONFLICT (symbol, interval, timestamp) DO NOTHING
                        """
                    ),
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "ts": candle.get("date"),
                        "o": candle.get("open"),
                        "h": candle.get("high"),
                        "l": candle.get("low"),
                        "c": candle.get("close"),
                        "v": candle.get("volume", 0),
                        "org_id": org_id,
                    },
                )
                stored += 1
            conn.commit()

        return {
            "ok": True,
            "symbol": symbol,
            "interval": interval,
            "stored": stored,
            "source": "kite",
        }

    except Exception as exc:
        logger.error("ohlcv_kite_fetch_error symbol=%s error=%s", symbol, exc)
        return {"ok": False, "error": str(exc), "symbol": symbol}


def fetch_ohlcv_yfinance(symbol: str, days_back: int = 365, org_id: int = 1) -> dict[str, Any]:
    """Yahoo Finance fallback. NSE symbols get an automatic ``.NS`` suffix.

    Returns ``{"ok": True, "stored": N, "source": "yfinance"}`` on success.
    """
    try:
        import yfinance as yf  # type: ignore[import-not-found]
    except ImportError:
        return {"ok": False, "error": "yfinance_not_installed", "symbol": symbol}

    try:
        # Yahoo Finance does not expose NIFTY 50 under "NIFTY50.NS" — map to the index ticker.
        if symbol.upper() == "NIFTY50":
            yf_symbol = "^NSEI"
        elif symbol.endswith(".NS") or symbol.startswith("^"):
            yf_symbol = symbol
        else:
            yf_symbol = f"{symbol}.NS"

        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=f"{int(days_back)}d", interval="1d", auto_adjust=False)

        if df is None or df.empty:
            return {"ok": False, "error": "no_data", "symbol": symbol, "yf_symbol": yf_symbol}

        engine = get_engine()
        if engine is None:
            return {"ok": False, "error": "database_unavailable", "symbol": symbol}

        stored = 0
        with engine.connect() as conn:
            for ts, row in df.iterrows():
                try:
                    py_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else datetime.fromisoformat(str(ts))
                    conn.execute(
                        text(
                            """
                            INSERT INTO ohlcv_data
                            (symbol, interval, timestamp,
                             open, high, low, close, volume, org_id)
                            VALUES
                            (:symbol, :interval, :ts,
                             :o, :h, :l, :c, :v, :org_id)
                            ON CONFLICT (symbol, interval, timestamp) DO NOTHING
                            """
                        ),
                        {
                            "symbol": symbol,
                            "interval": "day",
                            "ts": py_ts,
                            "o": float(row["Open"]),
                            "h": float(row["High"]),
                            "l": float(row["Low"]),
                            "c": float(row["Close"]),
                            "v": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                            "org_id": int(org_id),
                        },
                    )
                    stored += 1
                except Exception as inner:
                    logger.debug("yfinance_row_skip symbol=%s err=%s", symbol, inner)
            conn.commit()

        return {"ok": True, "symbol": symbol, "stored": stored, "source": "yfinance", "yf_symbol": yf_symbol}

    except Exception as exc:
        logger.error("yfinance_error symbol=%s error=%s", symbol, exc)
        return {"ok": False, "error": str(exc), "symbol": symbol}


def fetch_default_symbols_yfinance(org_id: int = 1) -> dict[str, Any]:
    """Seed the top 10 NSE symbols via Yahoo Finance (one-shot bootstrap)."""
    symbols = [
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "ICICIBANK",
        "WIPRO",
        "BAJFINANCE",
        "NIFTY50",
        "ADANIENT",
        # Yahoo no longer returns TATAMOTORS.NS reliably after ticker changes.
        # SBIN keeps the default yfinance seed set at 10 active symbols.
        "SBIN",
    ]
    results: list[dict[str, Any]] = []
    for symbol in symbols:
        r = fetch_ohlcv_yfinance(symbol, days_back=365, org_id=org_id)
        results.append(r)
        logger.info("seeded symbol=%s result=%s", symbol, r)
    return {
        "ok": True,
        "total": len(symbols),
        "stored_total": sum(int(r.get("stored") or 0) for r in results),
        "results": results,
    }


def fetch_and_store_ohlcv(
    symbol: str,
    interval: str = "day",
    days_back: int = 365,
    org_id: int = 1,
) -> dict[str, Any]:
    """Try Kite first (when configured), then fall back to Yahoo Finance.

    The yfinance fallback is only available for daily candles.
    Returns ``{"ok": False, ...}`` only when both data sources fail.
    """
    if _kite_credentials_present():
        kite_result = _fetch_kite(symbol, interval, days_back, org_id)
        if kite_result.get("ok"):
            return kite_result
        logger.info(
            "ohlcv_kite_failed_fallback_yfinance symbol=%s reason=%s",
            symbol,
            kite_result.get("error"),
        )

    if interval != "day":
        return {
            "ok": False,
            "error": "yfinance_supports_only_day_interval",
            "symbol": symbol,
            "interval": interval,
        }

    return fetch_ohlcv_yfinance(symbol, days_back=days_back, org_id=org_id)


def get_ohlcv(symbol: str, interval: str = "day", limit: int = 100) -> list[dict[str, Any]]:
    """Read OHLCV rows for a symbol/interval (newest first)."""
    try:
        engine = get_engine()
        if engine is None:
            return []
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv_data
                    WHERE symbol = :symbol AND interval = :interval
                    ORDER BY timestamp DESC
                    LIMIT :limit
                    """
                ),
                {"symbol": symbol, "interval": interval, "limit": limit},
            )
            return [
                {
                    "timestamp": str(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": int(r[5] or 0),
                }
                for r in rows
            ]
    except Exception as exc:
        logger.error("ohlcv_read_error symbol=%s error=%s", symbol, exc)
        return []


def get_default_symbols() -> list[str]:
    """Top NSE symbols tracked by the scheduled OHLCV fetcher."""
    return [
        "NIFTY50",
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "ICICIBANK",
        "WIPRO",
        "BAJFINANCE",
        "SBIN",
        "ADANIENT",
    ]


def store_summary() -> dict[str, Any]:
    """Lightweight status used by ``/personal/os/quant-status``."""
    out: dict[str, Any] = {
        "tables_exist": False,
        "symbol_count": 0,
        "total_candles": 0,
    }
    engine = get_engine()
    if engine is None:
        return out
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT symbol), COUNT(*)
                    FROM ohlcv_data
                    """
                )
            ).first()
            out["tables_exist"] = True
            out["symbol_count"] = int(row[0] or 0) if row else 0
            out["total_candles"] = int(row[1] or 0) if row else 0
    except Exception as exc:
        logger.debug("ohlcv_summary_unavailable: %s", exc)
    return out
