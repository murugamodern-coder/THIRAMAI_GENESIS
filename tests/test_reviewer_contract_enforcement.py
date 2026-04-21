from __future__ import annotations

import pytest

import thiramai.core.reviewer as reviewer_mod
from thiramai.core.reviewer import Reviewer


def test_reviewer_uses_fail_closed_fallback_on_invalid_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = Reviewer()

    def _raise_structured_error(*_args, **_kwargs):
        raise RuntimeError("invalid schema from llm")

    monkeypatch.setattr(reviewer_mod, "call_llm_structured", _raise_structured_error)

    task = {"type": "audit", "command": "git status", "success_criteria": "contains on branch"}
    result = {"status": "success", "output": "On branch main"}
    review = reviewer.review(task, result)

    assert review["status"] == "fail"
    assert review["confidence"] == 0.0
    assert "Structured reviewer validation failed" in review["reason"]
    assert review["suggested_fix"] == ""
