"""Default TTLs (seconds) for app-layer cache entries."""

from __future__ import annotations

import os


def _clamp_int(raw: str | None, default: int, *, lo: int = 1, hi: int = 86400) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(lo, min(int(str(raw).strip()), hi))
    except ValueError:
        return default


def today_brief_ttl_seconds() -> int:
    """Today unified brief (personal + business cross-domain); env ``THIRAMAI_TODAY_BRIEF_CACHE_SEC``."""
    return _clamp_int(os.getenv("THIRAMAI_TODAY_BRIEF_CACHE_SEC"), 45, lo=0, hi=600)


def research_market_ttl_seconds() -> int:
    """Research / market snippets; override via env when wired to ``get_or_set_cache``."""
    return _clamp_int(os.getenv("THIRAMAI_RESEARCH_CACHE_SEC"), 300, lo=30, hi=3600)


def stock_quote_ttl_seconds() -> int:
    """Aligned with ``THIRAMAI_STOCK_QUOTE_CACHE_SEC`` in stock service."""
    return _clamp_int(os.getenv("THIRAMAI_STOCK_QUOTE_CACHE_SEC"), 60, lo=15, hi=600)
