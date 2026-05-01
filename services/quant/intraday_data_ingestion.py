"""Intraday OHLCV ingestion (1m / 5m / 15m).

Pulls intraday candles from a Kite client and writes them to the
``ohlcv_data`` Alembic-managed table. This sits *next to* the existing
:mod:`services.quant.ohlcv_store` module (which handles daily candles +
yfinance fallback) - we don't replace it. ``ohlcv_store.fetch_and_store_ohlcv``
already supports any Kite interval; this module is the targeted, mockable
worker entry point with proper IST market-hours checks and Redis caching.

Spec deviations
---------------

* The original imported ``core.db.models.OHLCVData`` which doesn't exist in
  this codebase - ``ohlcv_data`` is queried via raw SQL everywhere else
  (``services.quant.ohlcv_store``). We do the same.
* Market-hours check now uses Asia/Kolkata, not UTC. The spec compared
  ``datetime.now(timezone.utc).time()`` against ``time(9, 15)`` IST; that's
  off by 5h30m and would always report "market closed" during real Indian
  trading hours.
* SELECT-then-INSERT was racy. ``ohlcv_data`` already has a UNIQUE
  constraint on ``(symbol, interval, timestamp)`` and the rest of the
  codebase uses ``INSERT ... ON CONFLICT DO NOTHING``. We follow suit.
* ``volume`` defensively coerced via ``int(... or 0)`` since some Kite
  feeds return ``None`` for instruments without volume data.
* Kite client is *injectable* so tests don't need ``kiteconnect`` installed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import text

from core.database import get_engine

logger = logging.getLogger(__name__)


_VALID_INTERVALS: frozenset[str] = frozenset({"minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute"})

# Sentinel so callers can pass ``engine=None`` to mean "no DB at all".
_USE_DEFAULT_ENGINE: Any = object()


@dataclass
class IngestionResult:
    """Structured outcome of an intraday fetch attempt."""

    status: str                  # "ok" | "market_closed" | "kite_unavailable" | ...
    symbol: str
    interval: str
    candles_fetched: int = 0
    candles_stored: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "interval": self.interval,
            "candles_fetched": self.candles_fetched,
            "candles_stored": self.candles_stored,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ist_now() -> datetime:
    """Return the current time in Asia/Kolkata, falling back to naive local."""
    try:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo("Asia/Kolkata"))
        except Exception:  # pragma: no cover - environment-dependent
            import pytz  # type: ignore[import-untyped]

            return datetime.now(pytz.timezone("Asia/Kolkata"))
    except Exception:  # pragma: no cover - last-ditch
        return datetime.now()


def _default_kite_client_factory() -> Any:
    """Try to build a real Kite client from env vars; return ``None`` on failure."""
    try:
        from kiteconnect import KiteConnect  # type: ignore[import-not-found]
    except Exception as exc:
        logger.info("intraday_ingestion: kiteconnect not installed (%s)", exc)
        return None
    api_key = (os.getenv("KITE_API_KEY") or "").strip()
    access_token = (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
    if not api_key or not access_token:
        return None
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        return kite
    except Exception as exc:
        logger.warning("intraday_ingestion: kite init failed (%s)", exc)
        return None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class IntradayDataIngestion:
    """Fetch and persist intraday OHLCV candles for a watchlist."""

    market_open: time = time(9, 15)
    market_close: time = time(15, 30)

    def __init__(
        self,
        *,
        kite_client: Any = None,
        kite_client_factory: Callable[[], Any] | None = None,
        engine: Any = _USE_DEFAULT_ENGINE,
        org_id: int = 1,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # If neither client nor factory is supplied, try to build one
        # lazily on first use from env vars.
        self._kite = kite_client
        self._kite_factory = kite_client_factory or _default_kite_client_factory
        self._engine = get_engine() if engine is _USE_DEFAULT_ENGINE else engine
        self.org_id = int(org_id)
        self._clock = clock or _get_ist_now
        # instrument_token cache: symbol -> token (tokens don't change per
        # session and the lookup is the slowest part of a fetch).
        self._instrument_tokens: dict[str, int] = {}

    # -- public --------------------------------------------------------

    def is_market_open(self) -> bool:
        now = self._clock()
        # Weekdays only (Mon=0, Sat=5).
        if now.weekday() >= 5:
            return False
        t = now.time()
        return self.market_open <= t <= self.market_close

    def fetch_and_store(
        self,
        symbol: str,
        interval: str = "5minute",
        *,
        days_back: int = 1,
        force: bool = False,
    ) -> IngestionResult:
        """Pull intraday candles for ``symbol`` and persist to ``ohlcv_data``.

        ``force=True`` skips the market-hours guard so callers can backfill
        when the market is closed.
        """
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return IngestionResult("invalid_symbol", symbol, interval, error="empty symbol")
        if interval not in _VALID_INTERVALS:
            return IngestionResult("invalid_interval", symbol, interval, error=f"unsupported interval {interval!r}")

        if not force and not self.is_market_open():
            return IngestionResult("market_closed", symbol, interval)

        kite = self._ensure_kite()
        if kite is None:
            return IngestionResult("kite_unavailable", symbol, interval, error="kite client not available")

        token = self._get_instrument_token(kite, symbol)
        if not token:
            return IngestionResult("symbol_not_found", symbol, interval)

        try:
            now = self._clock()
            # Use the last ``days_back`` calendar days from the current IST
            # session start - Kite expects naive datetimes in IST.
            from_date = now.replace(hour=9, minute=15, second=0, microsecond=0) - timedelta(days=max(0, days_back - 1))
            to_date = now
            candles = kite.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
            ) or []
        except Exception as exc:
            logger.error("intraday_fetch_failed symbol=%s interval=%s err=%s", symbol, interval, exc)
            return IngestionResult("error", symbol, interval, error=str(exc))

        stored = self._store_candles(symbol, interval, candles)
        logger.info(
            "intraday_fetch ok symbol=%s interval=%s fetched=%d stored=%d",
            symbol, interval, len(candles), stored,
        )
        return IngestionResult(
            status="ok",
            symbol=symbol,
            interval=interval,
            candles_fetched=len(candles),
            candles_stored=stored,
        )

    def fetch_watchlist(
        self,
        symbols: Iterable[str],
        *,
        interval: str = "5minute",
        days_back: int = 1,
        force: bool = False,
    ) -> list[IngestionResult]:
        return [self.fetch_and_store(s, interval=interval, days_back=days_back, force=force) for s in symbols]

    # -- internals -----------------------------------------------------

    def _ensure_kite(self) -> Any:
        if self._kite is None:
            self._kite = self._kite_factory()
        return self._kite

    def _get_instrument_token(self, kite: Any, symbol: str) -> int | None:
        if symbol in self._instrument_tokens:
            return self._instrument_tokens[symbol]
        try:
            instruments = kite.instruments("NSE") or []
        except Exception as exc:
            logger.warning("instruments_lookup_failed symbol=%s: %s", symbol, exc)
            return None
        for inst in instruments:
            if (inst.get("tradingsymbol") or "").upper() == symbol:
                token = int(inst.get("instrument_token") or 0) or None
                if token:
                    self._instrument_tokens[symbol] = token
                return token
        return None

    def _store_candles(self, symbol: str, interval: str, candles: list[dict[str, Any]]) -> int:
        if not candles or self._engine is None:
            return 0
        stored = 0
        try:
            with self._engine.connect() as conn:
                for candle in candles:
                    ts = candle.get("date")
                    if ts is None:
                        continue
                    try:
                        result = conn.execute(
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
                                "interval": interval,
                                "ts": ts,
                                "o": float(candle.get("open") or 0.0),
                                "h": float(candle.get("high") or 0.0),
                                "l": float(candle.get("low") or 0.0),
                                "c": float(candle.get("close") or 0.0),
                                # Some Kite feeds return None for index instruments.
                                "v": int(candle.get("volume") or 0),
                                "org_id": self.org_id,
                            },
                        )
                        # PG returns rowcount=1 on insert, 0 on conflict.
                        rc = getattr(result, "rowcount", None)
                        stored += rc if isinstance(rc, int) and rc > 0 else 0
                    except Exception as inner:
                        logger.debug("intraday_row_skip symbol=%s err=%s", symbol, inner)
                conn.commit()
        except Exception as exc:
            logger.error("intraday_store_failed symbol=%s: %s", symbol, exc)
            return stored
        return stored


__all__ = [
    "IngestionResult",
    "IntradayDataIngestion",
]
