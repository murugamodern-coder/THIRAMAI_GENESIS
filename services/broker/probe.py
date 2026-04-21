"""Broker reachability probe used by orchestrator and health checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from services.broker.credentials import (
    broker_provider_for_user,
    fyers_configured_for_user,
    kite_configured_for_user,
)

_TIMEOUT_SECONDS = 3.0


def _probe_quote_sync(adapter) -> dict[str, Any]:
    return adapter.get_live_quotes(["RELIANCE"], exchange_suffix="NS")


def test_broker_connection(user_id: int, execution_mode: str = "live") -> dict[str, Any]:
    """
    Sync broker probe with hard 3s timeout.

    Returns:
      - {"ok": True, ...} when live broker quote path is reachable
      - {"ok": False, "reason": "..."} on any failure
    Never raises.
    """
    try:
        uid = int(user_id)
        mode = (execution_mode or "live").strip().lower()
        provider = broker_provider_for_user(uid)

        has_fyers = fyers_configured_for_user(uid)
        has_kite = kite_configured_for_user(uid)
        if not (has_fyers or has_kite):
            return {
                "ok": False,
                "reason": "no_credentials",
                "provider": provider,
            }

        from services.broker.factory import get_broker_adapter
        from services.broker.paper_adapter import PaperTradingAdapter

        adapter = get_broker_adapter(uid, execution_mode=mode if mode == "live" else "paper")
        if isinstance(adapter, PaperTradingAdapter) and mode == "live":
            return {
                "ok": False,
                "reason": "no_credentials",
                "provider": provider,
            }

        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_probe_quote_sync, adapter)
            try:
                quote = fut.result(timeout=_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                return {"ok": False, "error": "timeout", "provider": provider}

        if isinstance(quote, dict) and quote.get("ok") is not False:
            return {"ok": True, "provider": provider, "broker": getattr(adapter, "name", "unknown")}

        reason = "quote_probe_failed"
        if isinstance(quote, dict):
            reason = str(quote.get("error") or quote.get("reason") or reason)
        return {"ok": False, "error": reason[:300], "provider": provider}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
