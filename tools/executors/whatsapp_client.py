"""
WhatsApp / messaging stub for production alerts (e.g. Hollow Block daily goal).

Wire to Twilio / Meta Cloud API later. All sends are HIGH RISK — require HITL for bulk.
"""

from __future__ import annotations

import os
from typing import Any

from core.observability import log_action_engine, new_request_id


def send_production_alert(
    message: str,
    *,
    idempotency_key: str,
    to_e164: str | None = None,
) -> dict[str, Any]:
    """
    Stub alert channel. Example message:
    'Hollow Block: daily goal reached — blocks_out=480, labor within budget.'
    """
    rid = new_request_id()
    dest = to_e164 or os.getenv("WHATSAPP_ALERT_TO") or ""
    log_action_engine(
        rid,
        "whatsapp.alert_stub",
        action_type="whatsapp_alert_batch",
        idempotency_key=idempotency_key,
        risk_tier="high",
        ok=True,
        extra={"to": dest[:32], "preview": message[:160]},
    )
    return {
        "ok": True,
        "simulated": True,
        "to": dest or "(unset WHATSAPP_ALERT_TO)",
        "message_preview": message[:500],
    }


def hollow_block_goal_message(*, blocks_out: float, target: float, labor_inr: float | None) -> str:
    if blocks_out >= target:
        return (
            f"Hollow Block unit: **daily goal reached** — blocks_out={blocks_out:.0f} (target {target:.0f}). "
            f"Labor INR={labor_inr if labor_inr is not None else 'n/a'}."
        )
    return (
        f"Hollow Block unit: progress blocks_out={blocks_out:.0f} / target {target:.0f}. "
        "Keep pace for end-of-shift goal."
    )
