"""
SQL injection prevention: **parameterized queries only**.

Audit (static review):
- ``sqlalchemy.text()`` usages **must** bind all user/org input via ``:name`` parameters — never
  interpolate f-strings or ``%`` formatting into SQL text.
- **Audited OK:** ``services/predictive_engine.py`` — revenue/production queries use ``:oid`` binds.
- **Audited OK:** ``core/database.py`` — ``text("SELECT 1")`` is a constant health check.
- **Preferred:** ORM ``select(Model).where(Model.col == value)`` (SQLAlchemy escapes binds).

Call ``assert_text_uses_bound_parameters`` in tests if you add new ``text()`` SQL.
"""

from __future__ import annotations

import re
from typing import Any

# Disallow obvious string interpolation markers inside SQL text passed to ``text()``.
_FORBIDDEN_SQL_PATTERNS = (
    re.compile(r"%\s*\("),  # old-style % formatting
    re.compile(r"\$\d+"),  # some raw $1 placeholders without sqlalchemy
    re.compile(r"\{[^}]+\}"),  # f-string style {var} in SQL string
)


def assert_text_uses_bound_parameters(sql: str, *, bound_keys: set[str] | None = None) -> None:
    """
    Runtime guard for unit tests / CI: ensure ``sql`` has no obvious injection holes.

    Raises ``ValueError`` if forbidden patterns appear. Does not prove correctness — use with
    explicit ``bound_keys`` matching required ``:param`` names when provided.
    """
    for pat in _FORBIDDEN_SQL_PATTERNS:
        if pat.search(sql):
            raise ValueError(f"SQL text contains forbidden pattern: {pat.pattern}")
    if bound_keys:
        for key in bound_keys:
            if f":{key}" not in sql:
                raise ValueError(f"Expected bound parameter :{key} in SQL text")


def describe_raw_sql_audit() -> dict[str, Any]:
    """Machine-readable audit summary for ops / security reviews."""
    return {
        "policy": "No dynamic SQL fragments from user input; use bound parameters or ORM.",
        "audited_modules": [
            "services.predictive_engine (text + :oid)",
            "core.database (literal SELECT 1)",
        ],
    }
