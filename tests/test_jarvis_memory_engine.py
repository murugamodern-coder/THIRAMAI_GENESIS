"""Living Jarvis Upgrade 1 — context memory engine (keyword recall + prompt block)."""

from __future__ import annotations

from services.jarvis_memory_engine import (
    JarvisMemoryEngine,
    _auto_importance,
    _score_overlap,
    _tokenize,
)


def test_tokenize_splits_words() -> None:
    t = _tokenize("Solar PVC project in Chennai")
    assert "solar" in t and "chennai" in t


def test_score_overlap_respects_importance() -> None:
    q = _tokenize("solar financing")
    low = _score_overlap(q, "We discussed solar financing last week", importance=3)
    high = _score_overlap(q, "We discussed solar financing last week", importance=9)
    assert high > low


def test_auto_importance_boosts_urgent_language() -> None:
    assert _auto_importance("This is critical for our factory", "") >= 7


def test_format_memory_block_when_db_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr("services.jarvis_memory_engine.get_session_factory", lambda: None)
    eng = JarvisMemoryEngine()
    block = eng.format_memory_context_block(
        user_id=1,
        session_id="test-session",
        current_user_message="What about the solar idea from last week?",
    )
    assert "MEMORY CONTEXT" in block
    assert "Working memory" in block


def test_recall_returns_empty_without_db(monkeypatch) -> None:
    monkeypatch.setattr("services.jarvis_memory_engine.get_session_factory", lambda: None)
    eng = JarvisMemoryEngine()
    assert eng.recall(1, "solar panels", top_k=3) == []
