"""
Persist classified inbound messages to ``comms_inbox`` and optionally ``compliance_cases`` (Phase 5).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import ComplianceCase, CommsInbox


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def _dedupe_email_case_ref(message_id: str, subject: str, from_addr: str) -> str:
    raw = f"{message_id}|{subject[:200]}|{from_addr[:200]}"
    h = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"email_tax:{h}"


def _guess_gst_deadline_from_text(text: str) -> date | None:
    """Best-effort parse ``DD-MM-YYYY`` or ``YYYY-MM-DD`` near keywords."""
    blob = (text or "")[:4000]
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", blob):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    for m in re.finditer(r"\b(\d{2})-(\d{2})-(\d{4})\b", blob):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d)
        except ValueError:
            continue
    return None


def ingest_classified_email(
    *,
    organization_id: int,
    message_id: str,
    subject: str,
    from_addr: str,
    body_excerpt: str,
    intelligence_tier: str,
    source: str = "Email",
) -> dict[str, Any]:
    """
    Insert **comms_inbox** row; if tier is tax/compliance (``orange``), create linked **compliance_cases** row when new.

    ``intelligence_tier``: ``red`` | ``orange`` | ``yellow`` (internal keys; labels are emoji-tier in UI).
    """
    oid = int(organization_id)
    tier = (intelligence_tier or "").strip().lower()[:32]
    mid = (message_id or "").strip()[:500] or "unknown"
    subj = (subject or "").strip()[:2000]
    sender = (from_addr or "").strip()[:2000]
    summary = (body_excerpt or "").strip()[:8000] or "(no body)"

    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database_unavailable"}

    related_id: int | None = None
    with factory() as session:
        with session.begin():
            existing_inbox = session.execute(
                select(CommsInbox.id).where(
                    CommsInbox.organization_id == oid,
                    CommsInbox.message_id == mid,
                ).limit(1)
            ).scalar_one_or_none()
            if existing_inbox is not None:
                return {"ok": True, "deduped": True, "comms_inbox_id": int(existing_inbox), "related_case_id": None}

            if tier == "orange":
                ext = _dedupe_email_case_ref(mid, subj, sender)
                case = session.execute(
                    select(ComplianceCase).where(
                        ComplianceCase.organization_id == oid,
                        ComplianceCase.external_ref == ext,
                    ).limit(1)
                ).scalar_one_or_none()
                if case is None:
                    dl = _guess_gst_deadline_from_text(f"{subj}\n{summary}")
                    case = ComplianceCase(
                        organization_id=oid,
                        title=subj[:2000] or "Tax / compliance — inbound email",
                        category="GST",
                        priority="high",
                        deadline=dl,
                        status="open",
                        external_ref=ext,
                    )
                    session.add(case)
                    session.flush()
                related_id = int(case.id)

            row = CommsInbox(
                organization_id=oid,
                source=(source or "Email")[:32],
                sender=sender,
                subject=subj,
                body_summary=summary,
                intelligence_tier=tier or None,
                related_case_id=related_id,
                message_id=mid,
            )
            session.add(row)
            session.flush()
            return {"ok": True, "deduped": False, "comms_inbox_id": int(row.id), "related_case_id": related_id}

    return {"ok": False, "error": "unknown"}
