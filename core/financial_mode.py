"""
Financial presentation mode: KPI / narrative vs strict accounting semantics.

``insight`` (default): management KPIs may mix documented bases (e.g. tax-inclusive revenue vs pre-tax COGS).
``accounting``: callers must not present mixed bases as filing-grade; economics APIs surface explicit flags.
"""

from __future__ import annotations

import os

MODE_INSIGHT = "insight"
MODE_ACCOUNTING = "accounting"


def get_financial_mode() -> str:
    raw = (os.getenv("THIRAMAI_FINANCIAL_MODE") or MODE_INSIGHT).strip().lower()
    return MODE_ACCOUNTING if raw == MODE_ACCOUNTING else MODE_INSIGHT


def is_accounting_strict() -> bool:
    return get_financial_mode() == MODE_ACCOUNTING
