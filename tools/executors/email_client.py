"""
Email executor — Gmail / Outlook style integration (stub + extension points).

Inbound classification + IMAP: see ``tools.email_reader`` (JARVIS Eye). This module stays focused on
outbound stubs / HITL.

Set env: EMAIL_PROVIDER=gmail|outlook, EMAIL_ACCESS_TOKEN or app-password flows (implement per tenant).
Do not commit secrets. High-risk sends should go through services.approval_store (HITL).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from core.observability import log_action_engine, new_request_id


@dataclass
class InboundOrderHint:
    """Parsed hint from an email thread (filled by future IMAP/Graph fetch)."""

    subject: str
    sender: str
    body_excerpt: str
    message_id: str | None = None


def fetch_incoming_order_hints(*, max_items: int = 10) -> list[InboundOrderHint]:
    """
    Stub: returns empty list until OAuth/IMAP is wired.
    Replace with Gmail API or Microsoft Graph list messages + filter.
    """
    _ = max_items
    if not (os.getenv("EMAIL_ACCESS_TOKEN") or os.getenv("EMAIL_IMAP_HOST")):
        return []
    return []


def draft_reply_for_order(hint: InboundOrderHint, *, sovereign_tone: str = "professional") -> str:
    """Stub LLM-free template for acknowledgement / quote request."""
    _ = sovereign_tone
    return (
        f"Subject: Re: {hint.subject}\n\n"
        f"Thank you for your inquiry. We are preparing a formal quotation and will revert within one business day.\n"
        f"(Automated draft — requires HITL before send.)\n"
    )


def send_email_stub(to: str, subject: str, body: str, *, idempotency_key: str) -> dict[str, Any]:
    """HIGH RISK — does not actually send without provider config; logs intent only."""
    rid = new_request_id()
    log_action_engine(
        rid,
        "email.send_stub",
        action_type="email_send",
        idempotency_key=idempotency_key,
        risk_tier="high",
        ok=True,
        extra={"to": to, "subject": subject[:120]},
    )
    return {
        "ok": True,
        "simulated": True,
        "detail": "Configure EMAIL_* env and replace stub with provider SDK; use approval_gate before real send.",
    }
