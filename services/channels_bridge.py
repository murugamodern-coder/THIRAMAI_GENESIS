"""
Stage 5 — Multi-channel persona with priority routing.

* **Low** — operational Q&A (machine status, simple facts): auto-reply via brain (short path).
* **High** — tax/legal/strategic forks: in-app ``Notification`` + optional Telegram / email / WhatsApp (Twilio).

Inbound webhooks should verify ``THIRAMAI_CHANNEL_WEBHOOK_SECRET``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Literal

import httpx
from sqlalchemy.dialects.postgresql import insert

from core.database import get_session_factory, session_scope
from core.db.models import Notification
from core.sovereign_journal import record_background_action, record_cot_step

_LOG = logging.getLogger(__name__)

NOTIFICATION_CONSTRAINT = "uq_notifications_org_dedupe"

HIGH_SIGNAL = frozenset(
    """
    tax gst vat legal law regulation compliance audit court lawsuit merger acquisition
    strategic board investor funding should i approve policy risk fine penalty statutory
    """.split()
)

LOW_SIGNAL = frozenset(
    """
    fixed machine status ok done running down error light temperature pressure
    inventory count stock level is the ready working
    """.split()
)


def classify_priority(text: str) -> Literal["low", "high"]:
    t = (text or "").lower()
    words = set(replace_punct(t).split())
    if words & HIGH_SIGNAL:
        return "high"
    if len(t) > 220 and ("?" in t) and any(w in t for w in ("should", "must", "required", "comply")):
        return "high"
    if words & LOW_SIGNAL and len(t) < 280:
        return "low"
    if len(t) < 160 and "?" in t:
        return "low"
    return "high"


def replace_punct(s: str) -> str:
    out = []
    for ch in s:
        out.append(" " if ch.isascii() and not ch.isalnum() and ch not in "_'" else ch)
    return " ".join("".join(out).split())


def send_telegram_text(*, text: str) -> dict[str, Any]:
    token = (os.getenv("THIRAMAI_TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("THIRAMAI_TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        return {"ok": False, "skipped": True, "reason": "telegram not configured"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = httpx.post(
            url,
            json={"chat_id": chat, "text": text[:4000], "parse_mode": "HTML"},
            timeout=30.0,
        )
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}", "body": r.text[:300]}
        return {"ok": True, "channel": "telegram"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def send_smtp_email(*, subject: str, body: str) -> dict[str, Any]:
    host = (os.getenv("THIRAMAI_SMTP_HOST") or "").strip()
    user = (os.getenv("THIRAMAI_SMTP_USER") or "").strip()
    pw = (os.getenv("THIRAMAI_SMTP_PASSWORD") or "").strip()
    to_addr = (os.getenv("THIRAMAI_ALERT_EMAIL_TO") or os.getenv("THIRAMAI_SMTP_TO") or "").strip()
    port = int((os.getenv("THIRAMAI_SMTP_PORT") or "587").strip() or "587")
    if not host or not to_addr:
        return {"ok": False, "skipped": True, "reason": "smtp not configured"}
    msg = EmailMessage()
    msg["Subject"] = subject[:200]
    msg["From"] = user or "thiramai@localhost"
    msg["To"] = to_addr
    msg.set_content(body[:12000])
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=45) as server:
            server.starttls(context=context)
            if user and pw:
                server.login(user, pw)
            server.send_message(msg)
        return {"ok": True, "channel": "smtp"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def send_whatsapp_twilio(*, body: str) -> dict[str, Any]:
    sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    from_n = (os.getenv("TWILIO_WHATSAPP_FROM") or "").strip()
    to_n = (os.getenv("TWILIO_WHATSAPP_TO") or "").strip()
    if not sid or not auth or not from_n or not to_n:
        return {"ok": False, "skipped": True, "reason": "twilio whatsapp not configured"}
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        r = httpx.post(
            url,
            auth=(sid, auth),
            data={"From": from_n, "To": to_n, "Body": body[:1600]},
            timeout=45.0,
        )
        if r.status_code >= 400:
            return {"ok": False, "error": r.text[:400]}
        return {"ok": True, "channel": "whatsapp_twilio"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def insert_priority_notification(
    *,
    organization_id: int,
    title: str,
    body_md: str,
    kind: str = "sovereign_high_priority",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no_database"}
    h = hashlib.sha256(f"{title}|{body_md[:400]}".encode("utf-8", errors="replace")).hexdigest()[:32]
    dedupe = f"{kind}:{h}"
    try:
        with session_scope() as session:
            stmt = insert(Notification).values(
                organization_id=int(organization_id),
                kind=kind[:64],
                severity="critical",
                title=title[:500],
                body=body_md[:8000],
                reference_type="sovereign",
                reference_id=None,
                payload=payload or {},
                dedupe_key=dedupe[:256],
            )
            stmt = stmt.on_conflict_do_nothing(constraint=NOTIFICATION_CONSTRAINT)
            res = session.execute(stmt)
            created = int(getattr(res, "rowcount", 0) or 0) > 0
        return {"ok": True, "notification_created": created}
    except Exception as exc:
        _LOG.warning("channels_bridge: notification insert failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def push_high_priority_alerts(*, organization_id: int, title: str, body: str) -> dict[str, Any]:
    """In-app row + best-effort outbound channels."""
    n = insert_priority_notification(organization_id=organization_id, title=title, body_md=body)
    out = {"notification": n, "channels": []}
    out["channels"].append(send_telegram_text(text=f"<b>{title}</b>\n{body}"[:4000]))
    out["channels"].append(send_smtp_email(subject=title, body=body))
    out["channels"].append(send_whatsapp_twilio(body=f"*{title}*\n{body}"))
    return out


def route_inbound_message(
    *,
    organization_id: int,
    channel: str,
    text: str,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Priority filter entrypoint. Low → brain narrative (caller must be allowed to invoke brain).
    High → notification + external push.
    """
    pri = classify_priority(text)
    record_cot_step(
        agent="channels_bridge",
        phase=f"inbound_{pri}",
        detail=f"{channel}: {text[:500]}",
        organization_id=int(organization_id),
        trace_id=trace_id,
    )
    if pri == "high":
        record_background_action(
            category="comms",
            summary=f"High-priority inbound ({channel}): {text[:400]}",
            organization_id=int(organization_id),
            meta={"channel": channel},
        )
        push = push_high_priority_alerts(
            organization_id=int(organization_id),
            title=f"Sovereign: decision needed ({channel})",
            body=f"**Inbound:**\n{text[:6000]}",
        )
        return {
            "priority": "high",
            "action": "escalated",
            "detail": "Routed to in-app notification and optional external channels.",
            "push": push,
        }

    # Low: return hint for caller to run brain (avoid circular import)
    return {
        "priority": "low",
        "action": "auto_reply_candidate",
        "detail": "Call brain.run_brain with this message for an automatic operational answer.",
        "suggested_pipeline": "run_brain",
    }


def verify_webhook_secret(header_value: str | None) -> bool:
    secret = (os.getenv("THIRAMAI_CHANNEL_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return False
    return (header_value or "").strip() == secret
