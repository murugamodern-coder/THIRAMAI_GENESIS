"""
THIRAMAI Options Execution Engine
Supports: Fyers + Kite (Zerodha)
Instruments: Nifty, Bank Nifty, Sensex options
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

_log = logging.getLogger("thiramai.options_executor")


class OptionType(str, Enum):
    CALL = "CE"
    PUT = "PE"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class OptionsOrder:
    symbol: str          # e.g. "NIFTY"
    expiry: str          # e.g. "2026-04-24"
    strike: float        # e.g. 22500.0
    option_type: OptionType  # CE or PE
    transaction_type: TransactionType
    quantity: int        # number of lots
    lot_size: int        # Nifty=50, BankNifty=15
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    tag: str = "THIRAMAI"


@dataclass
class OptionsOrderResult:
    success: bool
    order_id: Optional[str]
    broker: str
    symbol: str
    message: str
    raw_response: Optional[dict] = None

# Instrument configs for Indian indices
INSTRUMENT_CONFIG = {
    "NIFTY": {
        "lot_size": 50,
        "tick_size": 0.05,
        "fyers_prefix": "NSE:NIFTY",
        "kite_prefix": "NFO:NIFTY",
    },
    "BANKNIFTY": {
        "lot_size": 15,
        "tick_size": 0.05,
        "fyers_prefix": "NSE:BANKNIFTY",
        "kite_prefix": "NFO:BANKNIFTY",
    },
    "SENSEX": {
        "lot_size": 10,
        "tick_size": 0.05,
        "fyers_prefix": "BSE:SENSEX",
        "kite_prefix": "BFO:SENSEX",
    },
}

def build_fyers_symbol(symbol: str, expiry: str, strike: float, option_type: OptionType) -> str:
    """Build Fyers options symbol. e.g. NSE:NIFTY26APR2250024CE"""
    cfg = INSTRUMENT_CONFIG.get(symbol.upper(), {})
    prefix = cfg.get("fyers_prefix", f"NSE:{symbol.upper()}")
    # Format: PREFIX + YY + MON + STRIKE + CE/PE
    exp = datetime.strptime(expiry, "%Y-%m-%d")
    exp_str = exp.strftime("%y%b%d").upper()
    strike_str = str(int(strike))
    return f"{prefix}{exp_str}{strike_str}{option_type.value}"


def build_kite_symbol(symbol: str, expiry: str, strike: float, option_type: OptionType) -> str:
    """Build Kite/Zerodha options symbol."""
    exp = datetime.strptime(expiry, "%Y-%m-%d")
    exp_str = exp.strftime("%y%b").upper()
    strike_str = str(int(strike))
    return f"{symbol.upper()}{exp_str}{strike_str}{option_type.value}"


def _fyers_order_id(resp: Any) -> str | None:
    if not isinstance(resp, dict):
        return None
    if resp.get("id"):
        return str(resp["id"])
    data = resp.get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    if resp.get("order_id"):
        return str(resp["order_id"])
    return None


def _ensure_fyers_client(user_id: int):
    from services.broker.credentials import fyers_triplet

    client_id, _secret, token = fyers_triplet(int(user_id))
    if not (client_id and token):
        return None
    try:
        from fyers_apiv3 import fyersModel  # type: ignore[import-not-found]

        return fyersModel.FyersModel(client_id=client_id, token=token, log_path="")
    except Exception:
        _log.exception("Unable to initialize Fyers client")
        return None


def _ensure_kite_client(user_id: int):
    from services.broker.credentials import kite_triplet

    key, _secret, token = kite_triplet(int(user_id))
    if not (key and token):
        return None
    try:
        from kiteconnect import KiteConnect  # type: ignore[import-not-found]

        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        return kite
    except Exception:
        _log.exception("Unable to initialize Kite client")
        return None


async def execute_options_order_paper(order: OptionsOrder) -> OptionsOrderResult:
    """Paper trading — logs order, returns simulated order ID."""
    order_id = f"PAPER-{uuid.uuid4().hex[:8].upper()}"
    total_lots = order.quantity
    total_qty = total_lots * order.lot_size
    _log.info(
        "PAPER OPTIONS ORDER: %s %s %s %s strike=%.2f qty=%d lots=%d",
        order.transaction_type.value,
        order.symbol,
        order.expiry,
        order.option_type.value,
        order.strike,
        total_qty,
        total_lots,
    )
    return OptionsOrderResult(
        success=True,
        order_id=order_id,
        broker="paper",
        symbol=order.symbol,
        message=f"Paper order placed: {total_qty} qty @ {order.order_type.value}",
        raw_response={"paper": True, "qty": total_qty},
    )

async def execute_options_order_fyers(order: OptionsOrder, *, user_id: int) -> OptionsOrderResult:
    """Execute via Fyers broker."""
    try:
        fyers = _ensure_fyers_client(user_id)
        if not fyers:
            return OptionsOrderResult(
                success=False, order_id=None, broker="fyers",
                symbol=order.symbol, message="Fyers client not configured"
            )
        symbol = build_fyers_symbol(order.symbol, order.expiry, order.strike, order.option_type)
        payload = {
            "symbol": symbol,
            "qty": order.quantity * order.lot_size,
            "type": 2 if order.order_type == OrderType.MARKET else 1,
            "side": 1 if order.transaction_type == TransactionType.BUY else -1,
            "productType": "INTRADAY",
            "limitPrice": order.limit_price or 0,
            "stopPrice": order.stop_loss or 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
            "orderTag": order.tag,
        }
        response = fyers.place_order(data=payload)
        order_id = _fyers_order_id(response)
        if isinstance(response, dict) and response.get("s") == "ok" and order_id:
            return OptionsOrderResult(
                success=True,
                order_id=order_id,
                broker="fyers",
                symbol=symbol,
                message="Order placed successfully",
                raw_response=response,
            )
        return OptionsOrderResult(
            success=False, order_id=None, broker="fyers",
            symbol=symbol,
            message=(response or {}).get("message", "Unknown error") if isinstance(response, dict) else "Unknown error",
            raw_response=response,
        )
    except Exception as e:
        _log.error("Fyers options order failed: %s", e)
        return OptionsOrderResult(
            success=False, order_id=None, broker="fyers",
            symbol=order.symbol, message=str(e)
        )


async def execute_options_order_kite(order: OptionsOrder, *, user_id: int) -> OptionsOrderResult:
    """Execute via Zerodha Kite broker."""
    try:
        kite = _ensure_kite_client(user_id)
        if not kite:
            return OptionsOrderResult(
                success=False,
                order_id=None,
                broker="kite",
                symbol=order.symbol,
                message="Kite client not configured",
            )
        tradingsymbol = build_kite_symbol(order.symbol, order.expiry, order.strike, order.option_type)
        cfg = INSTRUMENT_CONFIG.get(order.symbol.upper(), {})
        exchange = "NFO"
        if str(cfg.get("kite_prefix", "")).startswith("BFO:"):
            exchange = "BFO"
        is_limit = order.order_type == OrderType.LIMIT
        order_type = kite.ORDER_TYPE_LIMIT if is_limit else kite.ORDER_TYPE_MARKET
        transaction_type = kite.TRANSACTION_TYPE_BUY if order.transaction_type == TransactionType.BUY else kite.TRANSACTION_TYPE_SELL
        params: dict[str, Any] = {
            "variety": kite.VARIETY_REGULAR,
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "transaction_type": transaction_type,
            "quantity": int(order.quantity * order.lot_size),
            "order_type": order_type,
            "product": kite.PRODUCT_MIS,
            "tag": order.tag,
        }
        if is_limit:
            if not order.limit_price or float(order.limit_price) <= 0:
                return OptionsOrderResult(
                    success=False,
                    order_id=None,
                    broker="kite",
                    symbol=tradingsymbol,
                    message="LIMIT order requires positive limit_price",
                )
            params["price"] = float(order.limit_price)
        order_id = kite.place_order(**params)
        oid = str(order_id).strip() if order_id else ""
        if oid:
            return OptionsOrderResult(
                success=True,
                order_id=oid,
                broker="kite",
                symbol=tradingsymbol,
                message="Order placed successfully",
                raw_response={"order_id": oid, "params": params},
            )
        return OptionsOrderResult(
            success=False,
            order_id=None,
            broker="kite",
            symbol=tradingsymbol,
            message="Broker returned empty order_id",
            raw_response={"params": params},
        )
    except Exception as e:
        _log.error("Kite options order failed: %s", e)
        return OptionsOrderResult(
            success=False,
            order_id=None,
            broker="kite",
            symbol=order.symbol,
            message=str(e),
        )


async def execute_options_order(
    order: OptionsOrder,
    *,
    user_id: int,
    mode: str = "paper",  # "paper", "fyers", "kite"
) -> OptionsOrderResult:
    """Main entry point for options execution."""
    _log.info("Options execution: mode=%s symbol=%s", mode, order.symbol)
    mode_norm = (mode or "paper").strip().lower()
    if mode_norm == "paper":
        return await execute_options_order_paper(order)
    if mode_norm == "fyers":
        return await execute_options_order_fyers(order, user_id=user_id)
    if mode_norm == "kite":
        return await execute_options_order_kite(order, user_id=user_id)
    return OptionsOrderResult(
        success=False, order_id=None, broker=mode_norm,
        symbol=order.symbol,
        message=f"Broker '{mode_norm}' not yet implemented"
    )
