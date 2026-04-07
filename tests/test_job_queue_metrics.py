"""Lightweight job queue helpers (no DB required when factory unset)."""

from __future__ import annotations

import services.job_queue as jq


def test_count_pending_jobs_zero_without_session_factory(monkeypatch):
    monkeypatch.setattr(jq, "get_session_factory", lambda: None)
    assert jq.count_pending_jobs() == 0
