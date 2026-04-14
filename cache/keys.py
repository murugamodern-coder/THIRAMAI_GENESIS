"""Stable hashed cache keys (prefix ``thiramai:appcache:``)."""

from __future__ import annotations

import hashlib


def build_stable_key(*parts: str) -> str:
    raw = ":".join(parts)
    h = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:40]
    return f"thiramai:appcache:{h}"


def key_today_brief(user_id: int, organization_id: int, day_iso: str) -> str:
    return build_stable_key("today_brief", str(int(user_id)), str(int(organization_id)), day_iso)


def key_research_market(user_id: int, organization_id: int, query: str) -> str:
    q = (query or "").strip()[:4000]
    return build_stable_key("research_market", str(int(user_id)), str(int(organization_id)), q)


def key_stock_quote(symbol_normalized: str) -> str:
    """Documented alias for ``thiramai:stock:price:*`` used in ``stock_market_data_service``."""
    return f"thiramai:stock:price:{symbol_normalized}"
