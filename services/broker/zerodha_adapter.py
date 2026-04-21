"""Zerodha Kite Connect adapter — skeleton; falls back to paper without API keys."""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

from services.broker.base import BaseBrokerAdapter
from services.broker.credentials import kite_configured_for_user, kite_triplet
from services.broker.equity_symbol_map import to_kite_equity
from services.broker.paper_adapter import PaperTradingAdapter

_log = logging.getLogger("thiramai.zerodha_adapter")


def _configured_env_only() -> bool:
    key = (os.getenv("KITE_API_KEY") or "").strip()
    secret = (os.getenv("KITE_API_SECRET") or "").strip()
    token = (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
    return bool(key and secret and token)


class ZerodhaAdapter(BaseBrokerAdapter):
    """Live broker via ``kiteconnect.KiteConnect`` when configured."""

    @staticmethod
    def is_configured() -> bool:
        return _configured_env_only()

    @staticmethod
    def is_configured_for_user(user_id: int) -> bool:
        return kite_configured_for_user(int(user_id))

    def __init__(self, user_id: int) -> None:
        super().__init__(user_id)
        self._kite: Any = None
        self._paper_fallback: PaperTradingAdapter | None = None

    def _ensure_kite(self) -> Any:
        if self._kite is not None:
            return self._kite
        if not kite_configured_for_user(self.user_id):
            return None
        try:
            from kiteconnect import KiteConnect  # type: ignore[import-not-found]

            key, _secret, token = kite_triplet(self.user_id)
            self._kite = KiteConnect(api_key=key)
            self._kite.set_access_token(token)
            return self._kite
        except Exception:
            return None

    def get_live_quotes(self, symbols: list[str], *, exchange_suffix: str = "NS") -> dict[str, Any]:
        k = self._ensure_kite()
        if k is None:
            return self._fallback_paper().get_live_quotes(symbols, exchange_suffix=exchange_suffix)
        quotes: dict[str, Any] = {}
        ok_any = False
        for raw in symbols:
            ex, ts = to_kite_equity(raw, exchange_suffix=exchange_suffix)
            if not ex or not ts:
                continue
            ikey = f"{ex}:{ts}"
            try:
                r = k.quote(ikey)
                row = r.get(ikey) if isinstance(r, dict) else None
                quotes[str(raw).strip().upper()] = row if isinstance(row, dict) else r
                if isinstance(row, dict) and row.get("last_price") is not None:
                    ok_any = True
            except Exception as exc:
                quotes[str(raw).strip().upper()] = {"ok": False, "error": str(exc)[:200]}
        return {"ok": ok_any, "broker": "ZerodhaAdapter", "quotes": quotes}

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        price_inr: Decimal | None,
        exchange_suffix: str = "NS",
        product_type: str = "CNC",
        order_type: str = "MARKET",
    ) -> dict[str, Any]:
        k = self._ensure_kite()
        if k is None:
            return self._fallback_paper().place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price_inr=price_inr,
                exchange_suffix=exchange_suffix,
                product_type=product_type,
                order_type=order_type,
            )
        exchange, tradingsymbol = to_kite_equity(symbol, exchange_suffix=exchange_suffix)
        if not exchange or not tradingsymbol:
            return {"ok": False, "error": "invalid_symbol", "broker": self.name, "symbol": symbol}
        side_l = (side or "").strip().lower()
        if side_l not in ("buy", "sell"):
            return {"ok": False, "error": f"unsupported side {side!r}", "broker": self.name}
        ot = (order_type or "MARKET").strip().upper()
        is_limit = ot == "LIMIT"
        prod = (product_type or "CNC").strip().upper()
        product = k.PRODUCT_CNC if prod == "CNC" else k.PRODUCT_MIS if prod == "MIS" else k.PRODUCT_CNC
        txn = k.TRANSACTION_TYPE_BUY if side_l == "buy" else k.TRANSACTION_TYPE_SELL
        otype = k.ORDER_TYPE_LIMIT if is_limit else k.ORDER_TYPE_MARKET
        params: dict[str, Any] = {
            "variety": k.VARIETY_REGULAR,
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "transaction_type": txn,
            "quantity": int(quantity),
            "order_type": otype,
            "product": product,
        }
        if is_limit:
            if price_inr is None:
                return {"ok": False, "error": "limit order requires price_inr", "broker": self.name}
            try:
                params["price"] = float(price_inr)
            except Exception:
                return {"ok": False, "error": "invalid limit price", "broker": self.name}
        try:
            order_id = k.place_order(**params)
        except Exception as exc:
            _log.exception("kite place_order failed")
            return {"ok": False, "error": str(exc)[:500], "broker": self.name, "exchange": exchange, "tradingsymbol": tradingsymbol}
        oid = str(order_id).strip() if order_id else ""
        if oid:
            return {
                "ok": True,
                "broker": self.name,
                "order_id": oid,
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
            }
        return {"ok": False, "error": "empty order_id", "broker": self.name}

    def get_positions(self) -> dict[str, Any]:
        k = self._ensure_kite()
        if k is None:
            return self._fallback_paper().get_positions()
        try:
            r = k.positions()
            return {"ok": True, "broker": self.name, "data": r if isinstance(r, dict) else {"raw": str(r)[:2000]}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "broker": self.name}

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        k = self._ensure_kite()
        if k is None:
            return {"ok": False, "error": "no session", "broker": "ZerodhaAdapter"}
        try:
            oid = k.cancel_order(variety=k.VARIETY_REGULAR, order_id=str(broker_order_id))
            return {"ok": True, "broker": self.name, "order_id": str(oid)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "broker_order_id": broker_order_id}

    def _fallback_paper(self) -> PaperTradingAdapter:
        if self._paper_fallback is None:
            self._paper_fallback = PaperTradingAdapter(self.user_id)
        return self._paper_fallback
