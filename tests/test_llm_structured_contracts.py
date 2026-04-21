from __future__ import annotations

import pytest

import thiramai.integrations.llm_clients as llm_clients
from thiramai.schemas.contracts import ReviewModel


def test_call_llm_structured_valid_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_clients,
        "multi_llm",
        lambda _prompt: '{"status":"pass","confidence":0.91,"reason":"ok","suggested_fix":""}',
    )

    parsed = llm_clients.call_llm_structured(ReviewModel, "review this")

    assert parsed.status == "pass"
    assert parsed.confidence == pytest.approx(0.91)
    assert parsed.reason == "ok"


def test_call_llm_structured_repair_path(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = iter(
        [
            '{"status":"pass","confidence":"bad-type","reason":"oops","suggested_fix":""}',
            '{"status":"fail","confidence":0.32,"reason":"repaired","suggested_fix":"git status"}',
        ]
    )
    monkeypatch.setattr(llm_clients, "multi_llm", lambda _prompt: next(outputs))

    parsed = llm_clients.call_llm_structured(ReviewModel, "review this")

    assert parsed.status == "fail"
    assert parsed.reason == "repaired"
    assert parsed.suggested_fix == "git status"


def test_call_llm_structured_raises_after_failed_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = iter(
        [
            '{"status":"unknown","confidence":"bad","reason":123,"suggested_fix":[]}',
            '{"status":"meh","confidence":"bad-again","reason":{},"suggested_fix":42}',
        ]
    )
    monkeypatch.setattr(llm_clients, "multi_llm", lambda _prompt: next(outputs))

    with pytest.raises(RuntimeError, match="Structured LLM response validation failed"):
        llm_clients.call_llm_structured(ReviewModel, "review this")
