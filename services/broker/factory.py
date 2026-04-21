"""Resolve broker adapter: paper vs live (Fyers / Zerodha) with credential fallback."""

from __future__ import annotations

import os

from services.broker.base import BaseBrokerAdapter
from services.broker.credentials import broker_provider_for_user
from services.broker.fyers_adapter import FyersAdapter
from services.broker.paper_adapter import PaperTradingAdapter
from services.broker.zerodha_adapter import ZerodhaAdapter


def get_broker_adapter(
    user_id: int,
    *,
    execution_mode: str = "paper",
    provider: str | None = None,
) -> BaseBrokerAdapter:
    """
    ``execution_mode``: ``paper`` | ``live``.
    ``live`` selects ``THIRAMAI_BROKER_PROVIDER`` (``fyers`` | ``zerodha``); missing SDK/keys → paper.
    """
    uid = int(user_id)
    mode = (execution_mode or "paper").strip().lower()
    if mode != "live":
        return PaperTradingAdapter(uid)

    prov = (provider or broker_provider_for_user(uid) or os.getenv("THIRAMAI_BROKER_PROVIDER") or "fyers").strip().lower()
    if prov == "zerodha":
        if ZerodhaAdapter.is_configured_for_user(uid):
            return ZerodhaAdapter(uid)
        return PaperTradingAdapter(uid)
    if prov == "fyers":
        if FyersAdapter.is_configured_for_user(uid):
            return FyersAdapter(uid)
        return PaperTradingAdapter(uid)

    return PaperTradingAdapter(uid)
