"""Abstract broker interface for live and paper execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any


class BaseBrokerAdapter(ABC):
    """Unified interface for quote, order, position, and cancel flows."""

    def __init__(self, user_id: int) -> None:
        self.user_id = int(user_id)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def get_live_quotes(self, symbols: list[str], *, exchange_suffix: str = "NS") -> dict[str, Any]:
        """Batch LTP / quote payload keyed by normalized symbol."""

    @abstractmethod
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
        """Place equity / cash order (product_type broker-specific where applicable)."""

    @abstractmethod
    def get_positions(self) -> dict[str, Any]:
        """Open positions / holdings summary."""

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        """Best-effort cancel by broker order id."""
