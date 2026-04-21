"""Map plain equity tickers to broker-native symbols (NSE/BSE cash)."""

from __future__ import annotations


def _root_ticker(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not s:
        return ""
    if ":" in s:
        tail = s.split(":")[-1]
        if tail.endswith("-EQ"):
            return tail[:-3]
        if tail.endswith("-BE") or tail.endswith("-BZ"):
            return tail[:-3]
        return tail
    return s


def to_fyers_symbol(symbol: str, *, exchange_suffix: str = "NS") -> str:
    """
    e.g. RELIANCE -> NSE:RELIANCE-EQ (NSE cash segment).
    ``exchange_suffix``: NS -> NSE, BO -> BSE.
    """
    root = _root_ticker(symbol)
    if not root:
        return ""
    ex = (exchange_suffix or "NS").strip().upper()
    if ex in ("BSE", "BO", "BS"):
        return f"BSE:{root}-EQ"
    return f"NSE:{root}-EQ"


def to_kite_equity(symbol: str, *, exchange_suffix: str = "NS") -> tuple[str, str]:
    """Returns (exchange, tradingsymbol) for Kite equity CNC/MIS orders."""
    root = _root_ticker(symbol)
    if not root:
        return "", ""
    ex = (exchange_suffix or "NS").strip().upper()
    if ex in ("BSE", "BO", "BS"):
        return "BSE", root
    return "NSE", root
