"""
Simple workflow automation rules (approval thresholds). Safe defaults; override via env.
"""

from __future__ import annotations

import os


def invoice_approval_threshold_inr() -> float:
    raw = (os.getenv("THIRAMAI_INVOICE_APPROVAL_THRESHOLD_INR") or "100000").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 100_000.0


def invoice_requires_approval(grand_total_inr: float) -> bool:
    """When True, ``POST /billing/create`` should enqueue HITL instead of posting immediately."""
    return float(grand_total_inr) > invoice_approval_threshold_inr()
