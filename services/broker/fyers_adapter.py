"""Fyers API v3 adapter — falls back to paper when SDK or credentials are missing."""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

from services.broker.base import BaseBrokerAdapter
from services.broker.credentials import fyers_configured_for_user, fyers_triplet
from services.broker.equity_symbol_map import to_fyers_symbol
from services.broker.paper_adapter import PaperTradingAdapter

_log = logging.getLogger("thiramai.fyers_adapter")


def _configured_env_only() -> bool:
    client_id = (os.getenv("FYERS_CLIENT_ID") or "").strip()
    secret = (os.getenv("FYERS_SECRET_KEY") or os.getenv("FYERS_SECRET") or "").strip()
    token = (os.getenv("FYERS_ACCESS_TOKEN") or "").strip()
    return bool(client_id and secret and token)


def _fyers_order_id(resp: Any) -> str | None:
    if not isinstance(resp, dict):
        return None
    if resp.get("s") == "ok" and resp.get("id"):
        return str(resp["id"])
    d = resp.get("data")
    if isinstance(d, dict) and d.get("id"):
        return str(d["id"])
    if resp.get("order_id"):
        return str(resp["order_id"])
    return None


class FyersAdapter(BaseBrokerAdapter):
    """
    Live broker via ``fyers_apiv3`` when installed and env set.
    Without credentials, instantiate ``PaperTradingAdapter`` via factory instead.
    """

    @staticmethod
    def is_configured() -> bool:
        return _configured_env_only()

    @staticmethod
    def is_configured_for_user(user_id: int) -> bool:
        return fyers_configured_for_user(int(user_id))

    def __init__(self, user_id: int) -> None:
        super().__init__(user_id)
        self._session = None
        self._paper_fallback: PaperTradingAdapter | None = None

    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        if not fyers_configured_for_user(self.user_id):
            return None
        try:
            from fyers_apiv3 import fyersModel  # type: ignore[import-not-found]

            client_id, _secret, token = fyers_triplet(self.user_id)
            self._session = fyersModel.FyersModel(client_id=client_id, token=token, log_path="")
            return self._session
        except Exception:
            return None

    def get_live_quotes(self, symbols: list[str], *, exchange_suffix: str = "NS") -> dict[str, Any]:
        fy = self._ensure_session()
        if fy is None:
            return self._fallback_paper().get_live_quotes(symbols, exchange_suffix=exchange_suffix)
        quotes: dict[str, Any] = {}
        ok_any = False
        mapped: list[tuple[str, str]] = []
        for raw in symbols:
            u = str(raw).strip().upper()
            fsym = to_fyers_symbol(raw, exchange_suffix=exchange_suffix)
            if fsym:
                mapped.append((u, fsym))
        if not mapped:
            return {"ok": False, "broker": "FyersAdapter", "error": "no_valid_symbols", "quotes": {}}
        sym_csv = ",".join(fsym for _u, fsym in mapped)
        try:
            r = fy.quotes(data={"symbols": sym_csv})
        except Exception as exc:
            return {"ok": False, "broker": "FyersAdapter", "error": str(exc)[:300], "quotes": {}}
        if not isinstance(r, dict):
            return {"ok": False, "broker": "FyersAdapter", "error": "unexpected_quote_response", "quotes": {}}
        if r.get("s") == "ok":
            ok_any = True
        d = r.get("d")
        if isinstance(d, list):
            by_fsym = {str(item.get("n") or item.get("symbol") or ""): item for item in d if isinstance(item, dict)}
            for u, fsym in mapped:
                quotes[u] = by_fsym.get(fsym, r)
        else:
            for u, fsym in mapped:
                quotes[u] = r
        return {
            "ok": ok_any,
            "broker": "FyersAdapter",
            "quotes": quotes,
        }

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
        fy = self._ensure_session()
        if fy is None:
            return self._fallback_paper().place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price_inr=price_inr,
                exchange_suffix=exchange_suffix,
                product_type=product_type,
                order_type=order_type,
            )
        fsym = to_fyers_symbol(symbol, exchange_suffix=exchange_suffix)
        if not fsym:
            return {"ok": False, "error": "invalid_symbol", "broker": self.name, "symbol": symbol}
        side_l = (side or "").strip().lower()
        side_int = 1 if side_l == "buy" else -1 if side_l == "sell" else 0
        if side_int == 0:
            return {"ok": False, "error": f"unsupported side {side!r}", "broker": self.name}
        ot = (order_type or "MARKET").strip().upper()
        is_limit = ot == "LIMIT"
        type_int = 1 if is_limit else 2
        lim = 0.0
        if is_limit and price_inr is not None:
            try:
                lim = float(price_inr)
            except Exception:
                lim = 0.0
        if is_limit and lim <= 0:
            return {"ok": False, "error": "limit order requires positive price_inr", "broker": self.name}
        prod = (product_type or "CNC").strip().upper()
        if prod not in ("CNC", "INTRADAY", "MARGIN", "CO", "BO"):
            prod = "CNC"
        data: dict[str, Any] = {
            "symbol": fsym,
            "qty": int(quantity),
            "type": type_int,
            "side": side_int,
            "productType": prod,
            "limitPrice": lim,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        try:
            resp = fy.place_order(data=data)
        except Exception as exc:
            _log.exception("fyers place_order failed")
            return {"ok": False, "error": str(exc)[:500], "broker": self.name, "symbol": fsym}
        if not isinstance(resp, dict):
            return {"ok": False, "error": "unexpected_response", "broker": self.name, "raw": str(resp)[:300]}
        oid = _fyers_order_id(resp)
        if resp.get("s") == "ok" and oid:
            return {
                "ok": True,
                "broker": self.name,
                "order_id": oid,
                "fyers_symbol": fsym,
                "raw": resp,
            }
        msg = str(resp.get("message") or resp.get("msg") or resp)[:500]
        return {"ok": False, "error": msg, "broker": self.name, "fyers_symbol": fsym, "raw": resp}

    def get_positions(self) -> dict[str, Any]:
        fy = self._ensure_session()
        if fy is None:
            return self._fallback_paper().get_positions()
        try:
            r = fy.positions()
            return {"ok": True, "broker": self.name, "data": r if isinstance(r, dict) else {"raw": str(r)[:2000]}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "broker": self.name}

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        fy = self._ensure_session()
        if fy is None:
            return {"ok": False, "error": "no live session", "broker": "FyersAdapter"}
        try:
            r = fy.cancel_order(data={"id": str(broker_order_id)})
            return {"ok": isinstance(r, dict) and r.get("s") == "ok", "broker": self.name, "raw": r}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "broker_order_id": broker_order_id}

    def _fallback_paper(self) -> PaperTradingAdapter:
        if self._paper_fallback is None:
            self._paper_fallback = PaperTradingAdapter(self.user_id)
        return self._paper_fallback
