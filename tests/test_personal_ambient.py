"""Ambient intelligence payload (Personal OS only)."""

from __future__ import annotations

from services.personal_ambient_sync import build_ambient_sync


def test_ambient_focus_lock_nudge_when_mission_open() -> None:
    payload = {
        "authenticated": True,
        "tasks": [{"id": 7, "title": "Buy stock"}],
        "reminders": [],
        "jarvis_memory": {},
    }
    guidance = {"focus_lock_target": {"mission_id": 7, "title": "Buy stock"}, "message": "Hello"}
    a = build_ambient_sync(payload, guidance)
    assert a["focus_lock_nudge"] and "Buy stock" in a["focus_lock_nudge"]
    assert a["voice_script"] == "Hello"


def test_ambient_no_nudge_when_mission_done() -> None:
    payload = {"authenticated": True, "tasks": [], "reminders": [], "jarvis_memory": {}}
    guidance = {"focus_lock_target": {"mission_id": 99, "title": "Old"}, "message": "Hi"}
    a = build_ambient_sync(payload, guidance)
    assert a["focus_lock_nudge"] is None
