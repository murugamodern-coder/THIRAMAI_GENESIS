"""Broker adapters — paper simulation and live broker SDK stubs (Fyers / Zerodha)."""

from services.broker.base import BaseBrokerAdapter
from services.broker.factory import get_broker_adapter

__all__ = ["BaseBrokerAdapter", "get_broker_adapter"]
