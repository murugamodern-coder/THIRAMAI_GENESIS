"""Internal paper portfolio — mirrors trades via ``portfolio_service``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.broker.base import BaseBrokerAdapter
from services.portfolio_service import add_stock_sync, get_portfolio_summary_sync, sell_stock_sync
from services.stock_market_data_service import get_live_price


class PaperTradingAdapter(BaseBrokerAdapter):
    """Simulated fills at last traded price from ``get_live_price``."""

    def get_live_quotes(self, symbols: list[str], *, exchange_suffix: str = "NS") -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "mode": "paper", "quotes": {}}
        for raw in symbols:
            sym = (raw or "").strip().upper().replace(".NS", "")
            if not sym:
                continue
            q = get_live_price(sym, exchange_suffix=exchange_suffix)
            out["quotes"][sym] = q
        return out

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
        uid = self.user_id
        if uid <= 0:
            return {"ok": False, "error": "invalid user", "broker": self.name}
        sym = (symbol or "").strip().upper().replace(".NS", "")
        if quantity <= 0:
            return {"ok": False, "error": "quantity must be positive", "broker": self.name}
        side_l = (side or "").strip().lower()
        px = price_inr
        if px is None or px <= 0:
            q = get_live_price(sym, exchange_suffix=exchange_suffix)
            if not q.get("ok"):
                return {"ok": False, "error": q.get("error") or "quote failed", "broker": self.name}
            try:
                px = Decimal(str(q.get("last")))
            except Exception:
                return {"ok": False, "error": "invalid last price", "broker": self.name}
        if side_l == "buy":
            r = add_stock_sync(uid, sym, Decimal(quantity), px, exchange_suffix=exchange_suffix)
            return {**r, "broker": self.name, "mode": "paper"}
        if side_l == "sell":
            r = sell_stock_sync(uid, sym, Decimal(quantity), px, exchange_suffix=exchange_suffix)
            return {**r, "broker": self.name, "mode": "paper"}
        return {"ok": False, "error": f"unsupported side {side!r}", "broker": self.name}

    def get_positions(self) -> dict[str, Any]:
        summ = get_portfolio_summary_sync(self.user_id)
        return {"ok": summ.get("ok", False), "broker": self.name, "mode": "paper", **summ}

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        return {"ok": False, "error": "paper adapter has no live order ids", "broker": self.name}
