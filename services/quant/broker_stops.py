"""Broker-side protective exits via Zerodha GTT (Good Till Triggered).

Exposes :class:`BrokerStopManager` for **single-leg sell** GTTs (typical
post-fill stop on a cash (CNC) long). When ``kiteconnect`` or credentials
are missing, :meth:`place_stop_loss` returns ``status=kite_unavailable``
instead of raising — mirrors :func:`services.broker.zerodha_adapter.get_kite_client`.

Zerodha's ``place_gtt`` expects ``orders[A].exchange`` and
``orders[A].tradingsymbol`` explicitly; the original spec omitted those
fields and would 400 on the live API.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    from kiteconnect import KiteConnect  # type: ignore[import-not-found]

    _KITE_IMPORT_OK = True
except Exception:  # pragma: no cover - optional dep
    KiteConnect = None  # type: ignore[misc, assignment]
    _KITE_IMPORT_OK = False


def _default_kite_factory() -> Any | None:
    try:
        from services.broker.zerodha_adapter import get_kite_client

        return get_kite_client()
    except Exception as exc:
        logger.debug("broker_stops: get_kite_client failed: %s", exc)
        return None


class BrokerStopManager:
    """Place / cancel single-leg sell GTT stops."""

    def __init__(
        self,
        *,
        kite_client: Any | None = None,
        kite_factory: Callable[[], Any | None] | None = None,
    ) -> None:
        self._kite = kite_client
        self._factory = kite_factory or _default_kite_factory

    def _client(self) -> Any | None:
        if self._kite is not None:
            return self._kite
        self._kite = self._factory()
        return self._kite

    @staticmethod
    def kite_sdk_available() -> bool:
        return bool(_KITE_IMPORT_OK)

    @staticmethod
    def env_credentials_present() -> bool:
        return bool(
            (os.getenv("KITE_API_KEY") or "").strip()
            and (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
        )

    def place_stop_loss(
        self,
        symbol: str,
        quantity: int,
        trigger_price: float,
        limit_price: float | None = None,
        *,
        exchange: str = "NSE",
        product: str = "CNC",
    ) -> dict[str, Any]:
        """Place a sell GTT triggered at ``trigger_price``.

        With ``limit_price``: SL-LIMIT child; without: SL-MARKET child (price 0).
        """
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"status": "error", "error": "empty symbol"}
        if quantity <= 0:
            return {"status": "error", "error": "quantity must be positive"}
        if trigger_price <= 0:
            return {"status": "error", "error": "trigger_price must be positive"}

        kite = self._client()
        if kite is None:
            return {"status": "kite_unavailable", "reason": "no_kite_client"}

        order_type = "LIMIT" if limit_price is not None else "MARKET"
        child_price = float(limit_price) if limit_price is not None else 0.0

        try:
            gtt_type = getattr(kite, "GTT_TYPE_SINGLE", "single")
            order_type_const = getattr(
                kite,
                f"ORDER_TYPE_{order_type}",
                order_type,
            )
            result = kite.place_gtt(
                trigger_type=gtt_type,
                tradingsymbol=symbol,
                exchange=exchange,
                trigger_values=[float(trigger_price)],
                last_price=float(trigger_price),
                orders=[
                    {
                        "exchange": exchange,
                        "tradingsymbol": symbol,
                        "transaction_type": kite.TRANSACTION_TYPE_SELL,
                        "quantity": int(quantity),
                        "order_type": order_type_const,
                        "product": product,
                        "price": child_price,
                    }
                ],
            )
            trigger_id = result.get("trigger_id") if isinstance(result, dict) else None
            logger.info(
                "broker_stop: GTT placed symbol=%s trigger=%s order_type=%s id=%s",
                symbol,
                trigger_price,
                order_type,
                trigger_id,
            )
            return {
                "status": "placed",
                "order_id": str(trigger_id) if trigger_id is not None else None,
                "trigger_id": trigger_id,
                "raw": result,
            }
        except Exception as exc:
            logger.error("broker_stop: place_gtt failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def cancel_gtt(self, trigger_id: int | str) -> dict[str, Any]:
        """Delete a GTT by trigger id."""
        kite = self._client()
        if kite is None:
            return {"status": "kite_unavailable"}
        try:
            kite.delete_gtt(int(trigger_id))
            return {"status": "cancelled", "trigger_id": int(trigger_id)}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


__all__ = ["BrokerStopManager"]
