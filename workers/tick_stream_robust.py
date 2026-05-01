"""Robust Kite tick stream with auto-reconnect.

This is an *additional* worker, not a replacement for
:mod:`workers.market_tick_stream`. The legacy ``MarketTickStream`` is left
in place for any consumers wired into ``get_tick_stream()``; the robust
variant is opt-in and adds:

* graceful degradation when ``KITE_API_KEY`` / ``KITE_ACCESS_TOKEN`` /
  ``kiteconnect`` are missing (constructor never raises);
* exponential-backoff auto-reconnect on the original websocket thread
  closing (each reconnect runs on a *fresh* thread so we never block the
  I/O thread we were notified by);
* hot-add / hot-remove of subscribed instrument tokens behind a lock;
* injectable ``ticker_factory`` and ``redis_client`` so unit tests don't
  need either dependency installed and don't talk to a real network.

Spec deviations
---------------

* Constructor raised ``ValueError`` when env vars were missing - that
  prevents the worker from being instantiated in dev/test, and broke the
  graceful-degradation contract used elsewhere in the codebase. We log
  + set ``self.is_disabled = True`` instead.
* The original ``_on_close`` called ``time.sleep(backoff)`` *on the
  websocket I/O callback thread* and then immediately retried
  ``self.kws.connect`` on the same closed ticker. We spawn a daemon
  reconnect thread so the I/O callback returns promptly, and we build a
  fresh ticker on each retry.
* ``self.tokens`` was a bare ``set`` mutated from multiple threads
  (callbacks + ``add_tokens`` callers) - we put it behind a lock.
* Annotations: spec used ``List`` / ``Dict`` without importing them.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time as _time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _default_ticker_factory(api_key: str, access_token: str) -> Any:
    """Construct a real ``KiteTicker`` if the SDK is installed; else ``None``."""
    try:
        from kiteconnect import KiteTicker  # type: ignore[import-not-found]
    except Exception as exc:
        logger.error("tick_stream_robust: kiteconnect not installed (%s)", exc)
        return None
    try:
        return KiteTicker(api_key, access_token)
    except Exception as exc:
        logger.error("tick_stream_robust: KiteTicker init failed (%s)", exc)
        return None


def _default_redis_factory() -> Any:
    """Build a Redis client from ``REDIS_URL``; return ``None`` on failure."""
    try:
        import redis  # type: ignore[import-not-found]
    except Exception as exc:
        logger.warning("tick_stream_robust: redis not installed (%s)", exc)
        return None
    try:
        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    except Exception as exc:
        logger.warning("tick_stream_robust: redis client init failed (%s)", exc)
        return None


class RobustTickStream:
    """Production-grade tick stream consumer with auto-reconnect."""

    DEFAULT_MAX_RECONNECTS: int = 10
    DEFAULT_MAX_BACKOFF_SECONDS: int = 60
    DEFAULT_TICK_HISTORY: int = 1000

    def __init__(
        self,
        *,
        api_key: str | None = None,
        access_token: str | None = None,
        ticker_factory: Callable[[str, str], Any] | None = None,
        redis_client: Any = None,
        redis_factory: Callable[[], Any] | None = None,
        max_reconnects: int = DEFAULT_MAX_RECONNECTS,
        max_backoff_seconds: int = DEFAULT_MAX_BACKOFF_SECONDS,
        tick_history: int = DEFAULT_TICK_HISTORY,
        sleep_func: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else (os.getenv("KITE_API_KEY") or "").strip()
        self.access_token = (
            access_token if access_token is not None else (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
        )
        self.is_disabled: bool = not (self.api_key and self.access_token)
        if self.is_disabled:
            logger.info("tick_stream_robust: disabled (KITE credentials missing)")

        self._ticker_factory = ticker_factory or _default_ticker_factory
        self._redis_factory = redis_factory or _default_redis_factory
        self._redis = redis_client  # may be None until first use

        self.max_reconnects = int(max_reconnects)
        self.max_backoff_seconds = int(max_backoff_seconds)
        self.tick_history = int(tick_history)
        self._sleep = sleep_func or _time.sleep

        self.kws: Any = None
        self._tokens: set[int] = set()
        self._tokens_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.is_running: bool = False
        self.reconnect_count: int = 0
        self.tick_count: int = 0
        self._on_tick_callback: Callable[[list[dict[str, Any]]], None] | None = None
        self._reconnect_thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------

    def start(
        self,
        tokens: Iterable[int],
        *,
        on_tick: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> dict[str, Any]:
        """Connect (non-blocking) and subscribe to ``tokens``."""
        if self.is_disabled:
            return {"ok": False, "reason": "kite_credentials_missing"}

        with self._tokens_lock:
            self._tokens = {int(t) for t in tokens}
        self._on_tick_callback = on_tick

        ticker = self._ticker_factory(self.api_key, self.access_token)
        if ticker is None:
            return {"ok": False, "reason": "ticker_factory_failed"}

        self._wire_ticker(ticker)

        with self._state_lock:
            self.kws = ticker
            self.is_running = True
            self.reconnect_count = 0
        try:
            ticker.connect(threaded=True)
        except Exception as exc:
            logger.error("tick_stream_robust: connect failed (%s)", exc)
            with self._state_lock:
                self.is_running = False
            return {"ok": False, "reason": "connect_failed", "error": str(exc)}

        with self._tokens_lock:
            token_count = len(self._tokens)
        logger.info("tick_stream_robust: started with %d tokens", token_count)
        return {"ok": True, "tokens": token_count}

    def stop(self) -> None:
        with self._state_lock:
            self.is_running = False
            ticker = self.kws
            self.kws = None
        if ticker is not None:
            try:
                ticker.close()
            except Exception:  # pragma: no cover - shutdown best-effort
                pass

    def status(self) -> dict[str, Any]:
        with self._tokens_lock:
            n = len(self._tokens)
        with self._state_lock:
            return {
                "ok": True,
                "is_running": bool(self.is_running),
                "is_disabled": bool(self.is_disabled),
                "tick_count": int(self.tick_count),
                "subscribed_tokens": n,
                "reconnect_count": int(self.reconnect_count),
            }

    # -- subscription management --------------------------------------

    def add_tokens(self, tokens: Iterable[int]) -> int:
        """Hot-add tokens; returns count actually added."""
        wanted = {int(t) for t in tokens}
        with self._tokens_lock:
            new_tokens = wanted - self._tokens
            if not new_tokens:
                return 0
            self._tokens |= new_tokens
        ticker = self._current_ticker()
        if ticker is not None:
            try:
                ticker.subscribe(list(new_tokens))
                ticker.set_mode(ticker.MODE_FULL, list(new_tokens))
            except Exception as exc:
                logger.warning("tick_stream_robust: add_tokens subscribe failed (%s)", exc)
        return len(new_tokens)

    def remove_tokens(self, tokens: Iterable[int]) -> int:
        """Hot-remove tokens; returns count actually removed."""
        wanted = {int(t) for t in tokens}
        with self._tokens_lock:
            to_remove = wanted & self._tokens
            if not to_remove:
                return 0
            self._tokens -= to_remove
        ticker = self._current_ticker()
        if ticker is not None:
            try:
                ticker.unsubscribe(list(to_remove))
            except Exception as exc:
                logger.warning("tick_stream_robust: remove_tokens unsubscribe failed (%s)", exc)
        return len(to_remove)

    @property
    def tokens(self) -> set[int]:
        with self._tokens_lock:
            return set(self._tokens)

    # -- internals -----------------------------------------------------

    def _current_ticker(self) -> Any:
        with self._state_lock:
            return self.kws

    def _wire_ticker(self, ticker: Any) -> None:
        ticker.on_ticks = self._on_ticks
        ticker.on_connect = self._on_connect
        ticker.on_close = self._on_close
        ticker.on_error = self._on_error

    def _on_connect(self, ws: Any, response: Any) -> None:
        with self._tokens_lock:
            tokens_snapshot = list(self._tokens)
        if tokens_snapshot:
            try:
                ws.subscribe(tokens_snapshot)
                ws.set_mode(ws.MODE_FULL, tokens_snapshot)
            except Exception as exc:
                logger.warning("tick_stream_robust: subscribe-on-connect failed (%s)", exc)
        with self._state_lock:
            self.reconnect_count = 0
        logger.info("tick_stream_robust: connected, subscribed=%d", len(tokens_snapshot))

    def _on_ticks(self, ws: Any, ticks: list[dict[str, Any]]) -> None:
        try:
            with self._state_lock:
                self.tick_count += len(ticks)
            for tick in ticks:
                self._store_tick(tick)
            if self._on_tick_callback is not None:
                try:
                    self._on_tick_callback(ticks)
                except Exception as exc:
                    logger.warning("tick_stream_robust: user callback raised (%s)", exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("tick_stream_robust: tick processing failed (%s)", exc)

    def _on_close(self, ws: Any, code: Any, reason: Any) -> None:
        logger.warning("tick_stream_robust: closed code=%s reason=%s", code, reason)
        with self._state_lock:
            should_reconnect = self.is_running and self.reconnect_count < self.max_reconnects
            if should_reconnect:
                self.reconnect_count += 1
                attempt = self.reconnect_count
            else:
                self.is_running = False
                attempt = self.reconnect_count
        if not should_reconnect:
            logger.error("tick_stream_robust: max reconnects reached, giving up")
            return
        # Spawn a *separate* thread so the websocket I/O callback returns
        # promptly. Sleeping on the I/O thread blocks cleanup and starves
        # subsequent close events.
        backoff = min(self.max_backoff_seconds, 2 ** attempt)
        thread = threading.Thread(
            target=self._reconnect_after_backoff,
            args=(attempt, backoff),
            name=f"tick-stream-reconnect-{attempt}",
            daemon=True,
        )
        with self._state_lock:
            self._reconnect_thread = thread
        thread.start()

    def _reconnect_after_backoff(self, attempt: int, backoff: int) -> None:
        logger.info("tick_stream_robust: reconnect attempt=%d in %ds", attempt, backoff)
        try:
            self._sleep(backoff)
        except Exception:  # pragma: no cover - defensive
            pass
        with self._state_lock:
            if not self.is_running:
                logger.info("tick_stream_robust: stop requested during backoff, abandoning reconnect")
                return
        # Build a *fresh* ticker - re-using a closed ticker is unreliable.
        ticker = self._ticker_factory(self.api_key, self.access_token)
        if ticker is None:
            logger.error("tick_stream_robust: ticker_factory returned None during reconnect")
            return
        self._wire_ticker(ticker)
        with self._state_lock:
            self.kws = ticker
        try:
            ticker.connect(threaded=True)
        except Exception as exc:
            logger.error("tick_stream_robust: reconnect connect failed (%s)", exc)

    def _on_error(self, ws: Any, code: Any, reason: Any) -> None:
        logger.error("tick_stream_robust: error code=%s reason=%s", code, reason)

    def _store_tick(self, tick: dict[str, Any]) -> None:
        token = tick.get("instrument_token")
        if token is None:
            return
        if self._redis is None:
            self._redis = self._redis_factory()
            if self._redis is None:
                return
        payload = {
            "instrument_token": int(token),
            "ltp": tick.get("last_price"),
            "volume": tick.get("volume"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            key = f"ticks:{int(token)}"
            self._redis.lpush(key, json.dumps(payload))
            if self.tick_history > 0:
                self._redis.ltrim(key, 0, self.tick_history - 1)
            # Also publish a compact LTP cache key for the legacy
            # MarketTickStream consumers that read ``tick:<token>``.
            try:
                ltp = tick.get("last_price")
                if ltp is not None:
                    self._redis.setex(f"tick:{int(token)}", 60, str(ltp))
            except Exception:  # pragma: no cover - cache best-effort
                pass
        except Exception as exc:
            logger.debug("tick_stream_robust: redis write failed (%s)", exc)


# ---------------------------------------------------------------------------
# Process-wide singleton (lazy)
# ---------------------------------------------------------------------------


_singleton: RobustTickStream | None = None
_singleton_lock = threading.Lock()


def get_robust_tick_stream() -> RobustTickStream:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = RobustTickStream()
    return _singleton


def reset_robust_tick_stream() -> None:
    """Test-only reset for the process-wide singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            try:
                _singleton.stop()
            except Exception:
                pass
        _singleton = None


__all__ = [
    "RobustTickStream",
    "get_robust_tick_stream",
    "reset_robust_tick_stream",
]
