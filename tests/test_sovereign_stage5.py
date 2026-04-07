"""Stage 5 — sovereign journal + channel priority (no network)."""

from __future__ import annotations

from pathlib import Path

from core import sovereign_journal
from services import channels_bridge


def test_classify_priority_low_vs_high():
    assert channels_bridge.classify_priority("Is the machine fixed yet?") == "low"
    assert channels_bridge.classify_priority("GST law changed — should I update billing?") == "high"


def test_sovereign_journal_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sovereign_journal, "_sovereign_dir", lambda: tmp_path)
    monkeypatch.setenv("THIRAMAI_SOVEREIGN_STAGE5", "1")
    sovereign_journal.record_cot_step(
        agent="test",
        phase="p1",
        detail="hello",
        organization_id=7,
        trace_id="t1",
    )
    rows = sovereign_journal.read_recent_cot(limit=10, organization_id=7)
    assert len(rows) == 1
    assert rows[0]["agent"] == "test"
    assert rows[0]["phase"] == "p1"
    assert rows[0].get("id")


def test_webhook_secret(monkeypatch):
    monkeypatch.setenv("THIRAMAI_CHANNEL_WEBHOOK_SECRET", "abc")
    assert channels_bridge.verify_webhook_secret("abc") is True
    assert channels_bridge.verify_webhook_secret("wrong") is False
