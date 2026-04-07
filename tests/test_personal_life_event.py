"""Life event body validation (POST /personal/life-event)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.routes.personal import LifeEventBody


def test_life_event_body_accepts_allowed_kinds() -> None:
    for k in ("goal", "habit", "decision", "reflection", "note"):
        b = LifeEventBody(kind=k, summary="Did the thing", payload={"ref": 1})
        assert b.kind == k
        assert b.payload == {"ref": 1}


def test_life_event_body_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        LifeEventBody.model_validate({"kind": "pattern", "summary": "x"})


def test_life_event_body_rejects_whitespace_only_summary() -> None:
    with pytest.raises(ValidationError):
        LifeEventBody(kind="note", summary="   ")


def test_life_event_body_strips_summary() -> None:
    b = LifeEventBody(kind="note", summary="  hello  ")
    assert b.summary == "hello"


def test_life_event_body_rejects_oversized_payload() -> None:
    huge = {"x": "y" * 20_000}
    with pytest.raises(ValidationError):
        LifeEventBody(kind="note", summary="ok", payload=huge)
