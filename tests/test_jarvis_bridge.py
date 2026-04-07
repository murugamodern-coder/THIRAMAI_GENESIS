"""JARVIS UI bridge: thought stream JSON + experience ticker endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from services.thought_stream import append_thought, read_thought_stream


def test_thought_stream_json_endpoint() -> None:
    c = TestClient(app)
    r = c.get("/logs/thought_stream.json")
    assert r.status_code == 200
    body = r.json()
    assert "thoughts" in body
    assert isinstance(body["thoughts"], list)


def test_thought_stream_append_and_read_roundtrip(tmp_path, monkeypatch) -> None:
    import services.thought_stream as ts

    monkeypatch.setattr(ts, "_LOGS", tmp_path)
    monkeypatch.setattr(ts, "_STREAM_PATH", tmp_path / "thought_stream.json")
    append_thought("Analyzing Monday peak… adjusting threshold to 12.", phase="autoscale")
    data = read_thought_stream()
    assert len(data.get("thoughts") or []) >= 1
    assert "Monday peak" in (data["thoughts"][-1].get("message") or "")


def test_recent_experiences_json_endpoint() -> None:
    c = TestClient(app)
    r = c.get("/dashboard/recent_experiences.json")
    assert r.status_code == 200
    body = r.json()
    assert body.get("schema") == "thiramai.recent_experiences.v1"
    assert "items" in body
    assert isinstance(body["items"], list)
