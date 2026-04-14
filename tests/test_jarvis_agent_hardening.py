"""Routing, HITL indices, ChatQuery validation, and agent loop helpers (no live Groq)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.jarvis_agent_service import TOOL_SPECS, _normalize_tool_call, _tool_call_id
from services.jarvis_router import classify_query, merge_route_tool_specs, route_jarvis_query, route_query


def test_classify_stock_vs_business_inventory():
    assert classify_query("Nifty RSI breakout today") == "stock"
    assert classify_query("low stock on SKU rice 10kg reorder") == "business"


def test_merge_route_tool_specs_subsets_tools():
    model, specs, cat = route_jarvis_query("Research PM-Kisan eligibility in Tamil Nadu", TOOL_SPECS)
    assert cat == "research"
    names = {s["function"]["name"] for s in specs}
    assert "research_topic" in names
    assert "create_invoice" not in names
    assert isinstance(model, str) and model


def test_route_query_includes_category():
    r = route_query("log my expense")
    assert r["category"] == "personal"
    assert "create_task" in r["tool_names"]


def test_tool_call_id_fallback():
    assert _tool_call_id({"id": "abc"}, "fb") == "abc"
    assert _tool_call_id({}, "fb") == "fb"


def test_normalize_tool_call_dict():
    n, a = _normalize_tool_call(
        {"type": "function", "id": "1", "function": {"name": "create_task", "arguments": '{"title":"x"}'}}
    )
    assert n == "create_task"
    assert a.get("title") == "x"


def test_chat_query_body_allows_empty_message_for_partial_hitl():
    from api.routes.ai_chat import ChatQueryBody

    b = ChatQueryBody(
        message="",
        agent_mode=True,
        agent_pending_id="pend_test",
        agent_reject_tool_index=0,
    )
    assert b.agent_reject_tool_index == 0


def test_chat_query_body_allows_empty_for_batch_confirm():
    from api.routes.ai_chat import ChatQueryBody

    b = ChatQueryBody(message="", agent_confirm=True, agent_pending_id="p2")
    assert b.agent_confirm is True


def test_run_agent_partial_reject(monkeypatch):
    from services import jarvis_agent_service as ja

    calls = [
        {"name": "create_task", "arguments": {"title": "a"}},
        {"name": "create_task", "arguments": {"title": "b"}},
    ]
    state: dict = {"peek": (calls, None)}

    def peek(pid, user_id):
        return state["peek"]

    def pset(pid, user_id, tool_calls, ttl_sec, context_organization_id=None):
        state["peek"] = (tool_calls, context_organization_id)

    def pdelete(pid, user_id):
        state["peek"] = None

    monkeypatch.setattr(ja, "pending_peek", peek)
    monkeypatch.setattr(ja, "pending_set", pset)
    monkeypatch.setattr(ja, "pending_delete", pdelete)

    user = MagicMock()
    user.id = 1
    out = ja.run_agent(
        message="",
        user=user,
        agent_confirm=False,
        agent_pending_id="x",
        agent_reject_tool_index=0,
    )
    assert out.get("needs_confirmation") is True
    assert len(out.get("proposals") or []) == 1
    assert state["peek"] and len(state["peek"][0]) == 1


def test_run_agent_partial_confirm_executes_one(monkeypatch):
    from services import jarvis_agent_service as ja

    calls = [
        {"name": "create_task", "arguments": {"title": "only"}},
    ]
    state: dict = {"peek": (calls, None)}

    monkeypatch.setattr(ja, "pending_peek", lambda pid, user_id: state["peek"])
    monkeypatch.setattr(ja, "pending_set", lambda *a, **k: None)
    monkeypatch.setattr(ja, "pending_delete", lambda *a, **k: None)

    def fake_safe(**kwargs):
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(ja, "execute_tool_safe", fake_safe)

    user = MagicMock()
    user.id = 42
    out = ja.run_agent(
        message="",
        user=user,
        agent_confirm=False,
        agent_pending_id="y",
        agent_confirm_tool_index=0,
    )
    assert out.get("needs_confirmation") is False
    assert out.get("agent_pending_id") in (None, "")
    tr = out.get("tool_results") or []
    assert len(tr) == 1
