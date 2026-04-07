"""
JARVIS Eye — inbound email fetch (IMAP) + classification.

**Legacy buckets:** Government/Tax, Customer Order, Spam (heuristics).

**Phase 5 intelligence tiers** (orchestrator / Groq when ``GROQ_API_KEY`` is set, else heuristic map):

- **🔴 Action Required** — urgent business action (orders, time-sensitive commercial).
- **🟠 Tax/Compliance** — GST / statutory / auditor tone (feeds ``compliance_cases`` via ingestion).
- **🟡 General Info** — other non-spam.

Configure (optional): ``EMAIL_IMAP_HOST``, ``EMAIL_IMAP_USER``, ``EMAIL_IMAP_PASSWORD`` (or
``EMAIL_APP_PASSWORD``), ``EMAIL_IMAP_PORT`` (default 993), ``EMAIL_IMAP_MAILBOX`` (default INBOX).

Does not send mail. Use ``tools.executors.email_client`` for outbound stubs/HITL flows.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import os
import re
from email.header import decode_header
from enum import Enum
from typing import Any

_log = logging.getLogger("thiramai.email_reader")


class EmailCategory(str, Enum):
    government_tax = "government_tax"
    customer_order = "customer_order"
    spam = "spam"


class EmailIntelligenceTier(str, Enum):
    """Internal keys stored on ``comms_inbox.intelligence_tier``."""

    action_required = "red"
    tax_compliance = "orange"
    general_info = "yellow"


TIER_DISPLAY: dict[str, str] = {
    EmailIntelligenceTier.action_required.value: "🔴 Action Required",
    EmailIntelligenceTier.tax_compliance.value: "🟠 Tax/Compliance",
    EmailIntelligenceTier.general_info.value: "🟡 General Info",
}


_GOV_TAX = frozenset(
    """
    gst g.s.t gstn cbic income tax itr tds tan traces efiling e-filing portal
    ministry of finance department of revenue excise customs duty assessment
    scrutiny notice demand order u/s section 74 129 show cause scn adjudication
    prosecution penalty interest default filing gstr gstr-1 gstr-3b cmp-08
    tax invoice mismatch itc reversal annual return
    """.split()
)

_ORDER = frozenset(
    """
    purchase order p.o. po number order no order# quotation quote proforma
    delivery dispatch shipment tracking awb lr number consignment sku qty quantity
    """.split()
)

_SPAM = frozenset(
    """
    unsubscribe click here winner lottery prize bitcoin crypto viagra cialis
    you've been selected act now limited time free money investment opportunity
    """.split()
)


def _norm_tokens(text: str) -> set[str]:
    t = re.sub(r"[^\w\s]+", " ", (text or "").lower())
    return {w for w in t.split() if len(w) > 1}


def classify_email(*, subject: str, from_addr: str, body: str) -> EmailCategory:
    """
    Heuristic triage (no ML). Tune keywords for your inbox; not legal/tax advice.
    """
    blob = f"{subject}\n{from_addr}\n{body}".lower()
    words = _norm_tokens(blob)

    if words & _SPAM or any(p in blob for p in ("unsubscribe", "view in browser", "opt out")):
        if not (words & _GOV_TAX) and "gst" not in blob:
            return EmailCategory.spam

    gov_hits = len(words & _GOV_TAX)
    if gov_hits >= 2 or any(
        p in blob
        for p in (
            "gst portal",
            "income tax",
            "cbic",
            "gstn",
            "government of india",
            "department of",
            "efiling",
            "traces",
        )
    ):
        return EmailCategory.government_tax
    if gov_hits == 1 and ("return" in blob or "filing" in blob or "tax" in blob):
        return EmailCategory.government_tax

    order_hits = len(words & _ORDER)
    if order_hits >= 2 or re.search(
        r"\b(po|p\.o\.)\s*[#:]?\s*\d+|\border\s*#?\s*\d+", blob, re.I
    ):
        return EmailCategory.customer_order
    if order_hits == 1 and re.search(r"\b\d+\s*(pcs|units|nos|kg|mt)\b", blob, re.I):
        return EmailCategory.customer_order

    if gov_hits == 1:
        return EmailCategory.government_tax

    return EmailCategory.spam


def classify_email_intelligence_ai(*, subject: str, from_addr: str, body: str) -> EmailIntelligenceTier | None:
    """
    Groq-based triage: exactly one of **RED** / **ORANGE** / **YELLOW** (returns ``None`` if no API / failure).

    RED ≈ 🔴 Action Required, ORANGE ≈ 🟠 Tax/Compliance, YELLOW ≈ 🟡 General Info.
    """
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return None
    try:
        from groq import Groq

        from core.policies.loader import GROQ_MODEL
    except Exception:
        return None

    excerpt = f"{subject}\n{from_addr}\n{(body or '')[:6000]}"
    sys = (
        "You classify inbound business email for JARVIS. Reply with exactly one token: "
        "RED, ORANGE, or YELLOW — no other words.\n"
        "RED = urgent business action required (PO, shipment, payment chase, legal demand from counterparty).\n"
        "ORANGE = tax, GST, CBIC, income tax, auditor, statutory notice, government portal, filing, compliance.\n"
        "YELLOW = general FYI newsletters, routine updates, low-urgency vendor mail.\n"
        "If the message is obvious spam or marketing noise, reply YELLOW."
    )
    try:
        client = Groq(api_key=key)
        comp = client.chat.completions.create(
            model=(os.getenv("GROQ_MODEL") or GROQ_MODEL),
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": excerpt},
            ],
            temperature=0.1,
            max_tokens=8,
        )
        raw = (comp.choices[0].message.content or "").strip().upper()
        if "ORANGE" in raw:
            return EmailIntelligenceTier.tax_compliance
        if "RED" in raw:
            return EmailIntelligenceTier.action_required
        if "YELLOW" in raw:
            return EmailIntelligenceTier.general_info
    except Exception as exc:
        _log.debug("email_intelligence_ai_failed: %s", exc)
    return None


def classify_email_intelligence(
    *,
    subject: str,
    from_addr: str,
    body: str,
    use_ai: bool = True,
) -> EmailIntelligenceTier | None:
    """
    Phase 5 tier for ingestion. Returns ``None`` for spam (skip comms row).

    Uses **AI orchestrator** (Groq) when ``use_ai`` and ``GROQ_API_KEY`` are set; else heuristic mapping
    from ``classify_email``.
    """
    cat = classify_email(subject=subject, from_addr=from_addr, body=body)
    if cat is EmailCategory.spam:
        return None
    if use_ai:
        ai_tier = classify_email_intelligence_ai(subject=subject, from_addr=from_addr, body=body)
        if ai_tier is not None:
            return ai_tier
    if cat is EmailCategory.government_tax:
        return EmailIntelligenceTier.tax_compliance
    if cat is EmailCategory.customer_order:
        return EmailIntelligenceTier.action_required
    return EmailIntelligenceTier.general_info


def tier_display_label(tier: EmailIntelligenceTier | str | None) -> str:
    if tier is None:
        return ""
    k = tier.value if isinstance(tier, EmailIntelligenceTier) else str(tier)
    return TIER_DISPLAY.get(k, k)


def jarvis_alert_tier(category: EmailCategory, subject: str, body: str) -> str:
    """
    Map to operational tier. Only **emergency** should trigger user push (see ``is_jarvis_emergency``).
    """
    if category is EmailCategory.spam:
        return "later"
    text = f"{subject}\n{body}".lower()
    subj = (subject or "").lower()

    if category is EmailCategory.government_tax:
        critical = (
            "notice",
            "demand",
            "penalty",
            "default",
            "assessment",
            "legal notice",
            "recovery",
            "prosecution",
            "show cause",
            "scn",
            "outstanding",
            "defaulter",
            "suspension",
            "cancellation",
            "last date",
            "due date",
            "due on",
            "before 15",
            "before 20",
            "gstr-3b",
            "gstr-1",
            "late fee",
        )
        if any(k in text for k in critical):
            return "emergency"
        return "urgent"

    if category is EmailCategory.customer_order:
        if any(k in subj for k in ("urgent", "rush", "asap", "critical")):
            return "emergency"
        if any(k in text for k in ("legal notice", "chargeback", "litigation", "court")):
            return "emergency"
        return "urgent"

    return "later"


def is_jarvis_emergency(category: EmailCategory, subject: str, body: str) -> bool:
    return jarvis_alert_tier(category, subject, body) == "emergency"


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _decode_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        plain: list[str] = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    plain.append(payload.decode(charset, errors="replace"))
        return "\n".join(plain)[:12000]
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")[:12000]


def _imap_configured() -> bool:
    host = (os.getenv("EMAIL_IMAP_HOST") or "").strip()
    user = (os.getenv("EMAIL_IMAP_USER") or os.getenv("EMAIL_USER") or "").strip()
    password = (
        (os.getenv("EMAIL_IMAP_PASSWORD") or os.getenv("EMAIL_APP_PASSWORD") or "").strip()
    )
    return bool(host and user and password)


def fetch_recent_emails_imap(*, max_items: int = 25) -> list[dict[str, Any]]:
    """
    Pull recent messages over IMAP (SSL). Returns minimal dicts for classification.

    Uses ``BODY.PEEK`` semantics via ``RFC822`` fetch (marks read depending on server; Gmail often
    still shows unread until \\Seen — we do not set \\Seen explicitly in this minimal client).
    """
    if not _imap_configured():
        return []
    host = (os.getenv("EMAIL_IMAP_HOST") or "").strip()
    user = (os.getenv("EMAIL_IMAP_USER") or os.getenv("EMAIL_USER") or "").strip()
    password = (
        (os.getenv("EMAIL_IMAP_PASSWORD") or os.getenv("EMAIL_APP_PASSWORD") or "").strip()
    )
    port = int((os.getenv("EMAIL_IMAP_PORT") or "993").strip() or "993")
    mailbox = (os.getenv("EMAIL_IMAP_MAILBOX") or "INBOX").strip() or "INBOX"
    use_ssl = (os.getenv("EMAIL_IMAP_USE_SSL") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )

    out: list[dict[str, Any]] = []
    try:
        if use_ssl:
            M = imaplib.IMAP4_SSL(host, port)
        else:
            M = imaplib.IMAP4(host, port)
        M.login(user, password)
        M.select(mailbox)
        typ, data = M.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            M.logout()
            return []
        ids = data[0].split()
        take = ids[-max(1, min(int(max_items), 100)) :]
        for num in take:
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(bytes(raw))
            subj = _decode_mime_header(msg.get("Subject", ""))
            from_ = _decode_mime_header(msg.get("From", ""))
            mid = (msg.get("Message-ID") or "").strip()
            if not mid:
                mid = f"hash:{hashlib.sha256(raw).hexdigest()[:24]}"
            body = _decode_body(msg)
            out.append(
                {
                    "message_id": mid,
                    "subject": subj,
                    "from": from_,
                    "body": body,
                    "raw_size": len(raw),
                }
            )
        M.logout()
    except Exception as exc:
        _log.warning("imap_fetch_failed: %s", exc, exc_info=True)
        return out
    return out
