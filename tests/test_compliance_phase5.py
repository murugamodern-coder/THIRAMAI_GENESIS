"""Phase 5 compliance calendar helpers (no DB)."""

from __future__ import annotations

import datetime as dt

from services.compliance_service import (
    _status_is_filing_done,
    deadline_for_month,
    days_until_deadline,
    external_ref_for_period,
    list_upcoming_statutory_context,
    planning_note_text,
)
from tools.email_reader import EmailIntelligenceTier, classify_email_intelligence


def test_deadline_for_month_february():
    from services.compliance_service import StatutoryRule

    r = StatutoryRule("t", "Test", 31, "GST")
    d = deadline_for_month(r, 2026, 2)
    assert d == dt.date(2026, 2, 28)


def test_days_until_and_external_ref():
    from services.compliance_service import StatutoryRule

    r = StatutoryRule("gstr1", "GSTR-1", 11, "GST")
    dl = deadline_for_month(r, 2026, 3)
    assert days_until_deadline(dt.date(2026, 3, 8), dl) == 3
    assert external_ref_for_period("gstr1", 2026, 3) == "statutory:gstr1:2026-03"


def test_list_upcoming_statutory_context_shape():
    rows = list_upcoming_statutory_context(dt.date(2026, 3, 1))
    assert isinstance(rows, list)
    assert all("external_ref" in x and "days_remaining" in x for x in rows)


def test_planning_note_text_for_orchestrator():
    text = planning_note_text(today=dt.date(2026, 3, 1))
    assert "Statutory" in text
    assert "GSTR" in text or "CMP" in text or "gst" in text.lower()


def test_classify_email_intelligence_heuristic_maps_tax(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    tier = classify_email_intelligence(
        subject="GST portal filing reminder GSTR-3B",
        from_addr="noreply@gst.gov.in",
        body="Please file your return before due date",
        use_ai=False,
    )
    assert tier is EmailIntelligenceTier.tax_compliance


def test_classify_email_intelligence_spam_is_none():
    tier = classify_email_intelligence(
        subject="Winner!!! Click here",
        from_addr="promo@spam.test",
        body="unsubscribe now lottery prize",
        use_ai=False,
    )
    assert tier is None


def test_filing_done_status_tokens():
    assert _status_is_filing_done("Filing Done")
    assert _status_is_filing_done("filing_done")
    assert _status_is_filing_done("closed")
    assert not _status_is_filing_done("open")
