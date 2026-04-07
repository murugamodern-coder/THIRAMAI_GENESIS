"""Dashboard NL command executor (Groq parse + corporate identity routing)."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.dashboard_command_executor import finalize_dashboard_command_response


@patch("services.dashboard_command_executor.persist_corporate_identity")
@patch("services.dashboard_command_executor._groq_extract_structured")
def test_command_execute_routes_to_persist_identity(
    mock_groq,
    mock_persist,
    monkeypatch,
) -> None:
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    mock_groq.return_value = {
        "action": "update_company_identity",
        "entity_name": "Modern Corporation",
        "value": "22AAAAA0000A1Z5",
        "confidence": 0.95,
        "rationale": "test",
    }
    mock_persist.return_value = {
        "organization_id": 1,
        "company_name": "Modern Corporation",
        "gst_number": "22AAAAA0000A1Z5",
    }

    c = TestClient(app)
    r = c.post("/dashboard/command/execute", json={"command": "add company Modern Corporation gst 22AAAAA0000A1Z5"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("executed") == "persist_corporate_identity"
    assert body.get("parsed", {}).get("entity_name") == "Modern Corporation"
    mock_persist.assert_called_once()
    call_kw = mock_persist.call_args
    assert call_kw[0][0] == 1
    assert "Modern Corporation" in str(call_kw)


def test_command_execute_accepts_trailing_slash(monkeypatch) -> None:
    """POST /dashboard/command/execute/ must resolve (avoids client/proxy 404)."""
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = TestClient(app)
    r = c.post("/dashboard/command/execute/", json={"command": "x"})
    assert r.status_code == 503


def test_command_execute_503_without_groq(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_AUTH_DISABLED", "1")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = TestClient(app)
    r = c.post("/dashboard/command/execute", json={"command": "hello"})
    assert r.status_code == 503


def test_finalize_dashboard_command_response_json_safe() -> None:
    out = finalize_dashboard_command_response(
        {
            "ok": True,
            "parsed": {"action": "update_company_identity", "entity_name": "Modern Corporation", "confidence": None},
            "result": {"company_name": "Modern Corporation", "amt": Decimal("99.50")},
            "executed": "persist_corporate_identity",
            "thought_message": "ok",
        }
    )
    json.dumps(out)
    assert out["parsed"]["rationale"] == ""
    assert out["parsed"]["confidence"] is None
    assert isinstance(out["result"]["amt"], str)


def test_finalize_dashboard_command_response_rejects_non_dict() -> None:
    fin = finalize_dashboard_command_response(None)
    assert fin["ok"] is False
    assert fin["error"] == "invalid_executor_response"
