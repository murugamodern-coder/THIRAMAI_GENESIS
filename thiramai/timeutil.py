"""UTC epoch helpers and monotonic-safe duration math (phase 59)."""

from __future__ import annotations

import time
from datetime import datetime, timezone


def utc_unix_now() -> float:
    """POSIX ``time.time()`` — epoch seconds aligned with UTC wall clock."""
    return time.time()


def utc_iso_from_unix(ts: float | None) -> str | None:
    """RFC 3339 UTC ``Z`` suffix from Unix epoch seconds."""
    if ts is None:
        return None
    try:
        return (
            datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def non_negative_ms(delta_ms: float) -> float:
    return max(0.0, float(delta_ms))
