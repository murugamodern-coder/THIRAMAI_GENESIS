"""Kite WebSocket tick stream worker.

Subscribes to ``KiteTicker`` and publishes the latest price for each instrument
into Redis (``tick:<instrument_token>``) so strategies can consume real-time
quotes without keeping a websocket open per consumer. Degrades gracefully when
``KITE_API_KEY`` / ``kiteconnect`` are not configured.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

KITE_ENABLED = bool((os.getenv("KITE_API_KEY") or "").strip())


class MarketTickStream:
    """Long-running websocket consumer that fans out ticks to Redis."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.subscribed_tokens: list[int] = []
        self.tick_count: int = 0
        self._kws: Any = None

    def start(self, instrument_tokens: list[int]) -> dict[str, Any]:
        if not KITE_ENABLED:
            logger.info("tick_stream_disabled: KITE_API_KEY not set")
            return {"ok": False, "reason": "kite_not_configured"}

        try:
            from kiteconnect import KiteTicker  # type: ignore[import-not-found]

            api_key = (os.getenv("KITE_API_KEY") or "").strip()
            access_token = (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
            if not api_key or not access_token:
                return {"ok": False, "reason": "kite_credentials_missing"}

            self._kws = KiteTicker(api_key, access_token)
            self.subscribed_tokens = list(instrument_tokens)

            def on_ticks(ws: Any, ticks: list[dict[str, Any]]) -> None:
                self.tick_count += len(ticks)
                self._process_ticks(ticks)

            def on_connect(ws: Any, response: Any) -> None:
                ws.subscribe(self.subscribed_tokens)
                ws.set_mode(ws.MODE_FULL, self.subscribed_tokens)
                logger.info("tick_stream_connected tokens=%d", len(self.subscribed_tokens))

            def on_error(ws: Any, code: int, reason: str) -> None:
                logger.error("tick_stream_error code=%s reason=%s", code, reason)

            def on_close(ws: Any, code: int, reason: str) -> None:
                logger.info("tick_stream_closed code=%s", code)
                self.is_running = False

            self._kws.on_ticks = on_ticks
            self._kws.on_connect = on_connect
            self._kws.on_error = on_error
            self._kws.on_close = on_close

            thread = threading.Thread(
                target=self._kws.connect,
                kwargs={"threaded": True},
                daemon=True,
            )
            thread.start()
            self.is_running = True
            return {"ok": True, "tokens": len(self.subscribed_tokens)}

        except ImportError:
            logger.warning("tick_stream_missing_dependency: kiteconnect not installed")
            return {"ok": False, "reason": "kiteconnect_missing"}
        except Exception as exc:
            logger.error("tick_stream_start_error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _process_ticks(self, ticks: list[dict[str, Any]]) -> None:
        try:
            import redis  # type: ignore[import-not-found]

            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            for tick in ticks:
                token = tick.get("instrument_token")
                if token is None:
                    continue
                price = tick.get("last_price", 0)
                r.setex(f"tick:{token}", 60, str(price))
        except Exception as exc:
            logger.warning("tick_store_error: %s", exc)

    def get_live_price(self, instrument_token: int) -> float:
        try:
            import redis  # type: ignore[import-not-found]

            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            price = r.get(f"tick:{instrument_token}")
            return float(price) if price else 0.0
        except Exception:
            return 0.0

    def stop(self) -> None:
        if self._kws is not None:
            try:
                self._kws.close()
            except Exception:
                pass
        self.is_running = False

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "is_running": bool(self.is_running),
            "tick_count": int(self.tick_count),
            "subscribed_tokens": len(self.subscribed_tokens),
            "kite_enabled": bool(KITE_ENABLED),
        }


tick_stream = MarketTickStream()


def get_tick_stream() -> MarketTickStream:
    return tick_stream
