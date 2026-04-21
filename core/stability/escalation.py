"""Escalate to incident / degraded mode when repeated failures or instability are detected."""

from __future__ import annotations

import os

from core.stability.logging_tags import log_stability


def maybe_escalate_incident_mode(
    *,
    reason: str,
    failure_count: int | None = None,
    unstable: bool = False,
) -> bool:
    """
    Set ``THIRAMAI_INCIDENT_MODE`` / ``THIRAMAI_STARTUP_DEGRADED`` when thresholds hit.
    Returns True if escalation was applied.
    """
    threshold = int(os.environ.get("THIRAMAI_STABILITY_ESCALATE_AFTER_FAILURES", "8") or "8")
    threshold = max(1, threshold)

    should = unstable
    if failure_count is not None and failure_count >= threshold:
        should = True

    if not should:
        return False

    os.environ["THIRAMAI_INCIDENT_MODE"] = "1"
    os.environ["THIRAMAI_STARTUP_DEGRADED"] = "1"
    if not (os.environ.get("THIRAMAI_SAFE_ERRORS") or "").strip():
        os.environ["THIRAMAI_SAFE_ERRORS"] = "1"
    log_stability(f"incident mode escalated: {reason}")
    return True
