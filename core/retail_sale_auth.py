"""
Retail POS / ``sell_stock`` auto-execution is restricted by role **name** (not hierarchy).

Default allow-list: ``admin``, ``staff``. Override with ``THIRAMAI_RETAIL_SALE_ROLES`` (comma-separated),
e.g. ``admin,staff,owner`` for local dev.
"""

from __future__ import annotations

import os


def _allowed_retail_sale_names() -> frozenset[str]:
    raw = (os.getenv("THIRAMAI_RETAIL_SALE_ROLES") or "admin,staff").strip().lower()
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return frozenset(parts) if parts else frozenset({"admin", "staff"})


def role_may_execute_retail_sale(role_name: str | None) -> bool:
    """True if ``role_name`` is in the configured allow-list (default: admin, staff)."""
    if not role_name:
        return False
    return role_name.strip().lower() in _allowed_retail_sale_names()
