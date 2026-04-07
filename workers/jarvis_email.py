"""
JARVIS Eye — hourly (configurable) IMAP poll: **emergency** tax/business mail → in-app notification.

Requires PostgreSQL ``notifications`` table. Set ``THIRAMAI_JARVIS_EMAIL_POLL=1`` and IMAP env vars
(see ``tools.email_reader``). Target org: ``THIRAMAI_JARVIS_ORG_ID`` or ``THIRAMAI_DEFAULT_ORG_ID`` (else 1).
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from core.database import get_session_factory, session_scope
from core.db.models import Notification
from core.observability import log_event, new_request_id
from services.comms_ingestion import ingest_classified_email
from services.jarvis_summarize import summarize_jarvis_emergency
from tools.email_reader import (
    EmailCategory,
    EmailIntelligenceTier,
    classify_email,
    classify_email_intelligence,
    fetch_recent_emails_imap,
    is_jarvis_emergency,
)

_log = logging.getLogger("thiramai.jarvis_email")

NOTIFICATION_CONSTRAINT = "uq_notifications_org_dedupe"


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def jarvis_email_poll_enabled() -> bool:
    return _truthy("THIRAMAI_JARVIS_EMAIL_POLL")


def jarvis_poll_interval_minutes() -> int:
    try:
        return max(15, int((os.getenv("THIRAMAI_JARVIS_EMAIL_INTERVAL_MINUTES") or "60").strip()))
    except ValueError:
        return 60


def _target_organization_id() -> int:
    for key in ("THIRAMAI_JARVIS_ORG_ID", "THIRAMAI_DEFAULT_ORG_ID"):
        raw = (os.getenv(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    return 1


def run_jarvis_email_scan() -> None:
    rid = new_request_id()
    if not jarvis_email_poll_enabled():
        return
    factory = get_session_factory()
    if factory is None:
        log_event(
            rid,
            "jarvis_email.skip",
            ok=False,
            extra={"reason": "no_database"},
        )
        return

    oid = _target_organization_id()
    max_fetch = int((os.getenv("THIRAMAI_JARVIS_EMAIL_MAX_FETCH") or "30").strip() or "30")
    max_fetch = max(5, min(max_fetch, 100))

    try:
        messages = fetch_recent_emails_imap(max_items=max_fetch)
    except Exception as exc:
        _log.exception("jarvis_email.fetch_failed")
        log_event(rid, "jarvis_email.fetch", ok=False, error=str(exc))
        return

    if not messages:
        log_event(
            rid,
            "jarvis_email.scan",
            ok=True,
            extra={"organization_id": oid, "fetched": 0, "emergency": 0},
        )
        return

    today_key = datetime.now(timezone.utc).date().isoformat()
    created = 0
    ingested = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        subj = str(m.get("subject") or "")
        body = str(m.get("body") or "")
        from_ = str(m.get("from") or "")
        mid = str(m.get("message_id") or "")
        cat = classify_email(subject=subj, from_addr=from_, body=body)
        tier = classify_email_intelligence(subject=subj, from_addr=from_, body=body, use_ai=True)
        if tier is not None:
            try:
                ing = ingest_classified_email(
                    organization_id=oid,
                    message_id=mid,
                    subject=subj,
                    from_addr=from_,
                    body_excerpt=body[:8000],
                    intelligence_tier=tier.value,
                    source="Email",
                )
                if ing.get("ok") and not ing.get("deduped"):
                    ingested += 1
            except Exception as exc:
                _log.warning("jarvis_email.ingest_failed: %s", exc, exc_info=True)

        if tier is EmailIntelligenceTier.tax_compliance and not is_jarvis_emergency(cat, subj, body):
            # Tax mail stored + compliance case; skip duplicate low-urgency push this cycle.
            continue
        if not is_jarvis_emergency(cat, subj, body):
            continue
        h = hashlib.sha256(f"{mid}|{subj[:200]}".encode("utf-8", errors="replace")).hexdigest()[:40]
        dedupe = f"jarvis_email:{h}:{today_key}"

        cat_label = "Government / Tax" if cat is EmailCategory.government_tax else "Customer / Business"
        ai_line = summarize_jarvis_emergency(
            subject=subj,
            body_excerpt=body[:4000],
            category_label=cat_label,
        )
        if ai_line:
            body_md = f"🔴 **JARVIS:** {ai_line}\n\n— {subj[:300]}"
        else:
            body_md = (
                f"🔴 **JARVIS (emergency):** {cat_label} message requires attention.\n\n"
                f"**Subject:** {subj[:400]}\n**From:** {from_[:200]}"
            )

        title = f"JARVIS: {cat_label} alert"
        payload: dict[str, Any] = {
            "message_id": mid,
            "category": cat.value,
            "from": from_[:500],
            "subject": subj[:500],
        }
        try:
            with session_scope() as session:
                stmt = insert(Notification).values(
                    organization_id=oid,
                    kind="jarvis_email_emergency",
                    severity="critical",
                    title=title,
                    body=body_md,
                    reference_type="email",
                    reference_id=None,
                    payload=payload,
                    dedupe_key=dedupe,
                )
                stmt = stmt.on_conflict_do_nothing(constraint=NOTIFICATION_CONSTRAINT)
                res = session.execute(stmt)
                if int(getattr(res, "rowcount", 0) or 0) > 0:
                    created += 1
        except Exception as exc:
            _log.warning("jarvis_email.notify_failed %s", exc, exc_info=True)

    log_event(
        rid,
        "jarvis_email.scan",
        ok=True,
        extra={
            "organization_id": oid,
            "fetched": len(messages),
            "notifications_created": created,
            "comms_rows_ingested": ingested,
        },
    )
