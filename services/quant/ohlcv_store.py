"""OHLCV historical data store.

Fetches and stores candlestick data from the configured Kite session
(``services.broker.zerodha_adapter.get_kite_client``). Designed to degrade gracefully
when Kite credentials are not configured or the optional ``kiteconnect`` SDK is missing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from core.database import get_engine

logger = logging.getLogger(__name__)


def fetch_and_store_ohlcv(
    symbol: str,
    interval: str = "day",
    days_back: int = 365,
    org_id: int = 1,
) -> dict[str, Any]:
    """Fetch OHLCV data from Kite and persist to ``ohlcv_data``.

    ``interval`` accepts Kite values ("minute", "5minute", "day", ...).
    Returns ``{"ok": False, "error": ...}`` on any failure (degraded mode is safe).
    """
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
            logger.warning("ohlcv_symbol_not_found symbol=%s", symbol)
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

        return {"ok": True, "symbol": symbol, "interval": interval, "stored": stored}

    except Exception as exc:
        logger.error("ohlcv_fetch_error symbol=%s error=%s", symbol, exc)
        return {"ok": False, "error": str(exc), "symbol": symbol}


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
        "TATAMOTORS",
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
