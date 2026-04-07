"""
Control whether automatic ``Base.metadata.create_all`` is allowed (dev convenience vs production discipline).
"""

from __future__ import annotations

import os


def allow_create_all_auto() -> bool:
    """
    When False, operators must use Alembic (``alembic upgrade head``) for PostgreSQL schema.

    Disabled when:
    - ``THIRAMAI_DISABLE_CREATE_ALL=1``, or
    - ``ENV`` / ``THIRAMAI_ENV`` is ``production``.
    """
    if (os.getenv("THIRAMAI_DISABLE_CREATE_ALL") or "").strip() == "1":
        return False
    env = (os.getenv("ENV") or os.getenv("THIRAMAI_ENV") or "").strip().lower()
    if env == "production":
        return False
    return True
