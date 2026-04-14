"""
Ambient intelligence payload for Personal OS — soft reminders and voice script hints.

No core ERP coupling; derives only from ``/personal/today`` aggregate + guidance.
"""

from __future__ import annotations

from typing import Any


def build_ambient_sync(payload: dict[str, Any], guidance: dict[str, Any]) -> dict[str, Any]:
    """
    Non-intrusive companion data:
    - ``background_reminders`` — up to 2 quiet lines (upcoming reminders, optional memory hint)
    - ``focus_lock_nudge`` — same-day gentle line if focus mission still open
    - ``voice_script`` — short text safe for optional browser TTS
    """
    out: dict[str, Any] = {
        "background_reminders": [],
        "focus_lock_nudge": None,
        "voice_script": None,
    }

    reminders = payload.get("reminders") if isinstance(payload.get("reminders"), list) else []
    for r in reminders[:2]:
        if not isinstance(r, dict):
            continue
        title = (r.get("title") or "").strip()
        if title:
            out["background_reminders"].append(f"Soft note — coming up: {title[:120]}")

    nudges = payload.get("meeting_nudges") if isinstance(payload.get("meeting_nudges"), list) else []
    for mn in nudges[:3]:
        if not isinstance(mn, dict):
            continue
        t = (mn.get("title") or "").strip()
        if not t:
            continue
        mu = mn.get("minutes_until")
        try:
            mui = int(mu) if mu is not None else None
        except (TypeError, ValueError):
            mui = None
        line = f"Meeting in {mui} min — {t[:100]}" if mui is not None else f"Meeting soon — {t[:100]}"
        if len(out["background_reminders"]) < 4:
            out["background_reminders"].append(line)

    if len(out["background_reminders"]) < 2 and payload.get("authenticated"):
        jm = payload.get("jarvis_memory") if isinstance(payload.get("jarvis_memory"), dict) else {}
        hint = jm.get("hint")
        if isinstance(hint, str) and hint.strip() and not out["background_reminders"]:
            out["background_reminders"].append(hint.strip()[:180])

    flt = guidance.get("focus_lock_target")
    tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    if isinstance(flt, dict) and flt.get("mission_id") is not None:
        try:
            mid = int(flt["mission_id"])
        except (TypeError, ValueError):
            mid = 0
        title = (flt.get("title") or "").strip() or "your focus task"
        open_ids = {int(t.get("id") or 0) for t in tasks if isinstance(t, dict)}
        if mid > 0 and mid in open_ids:
            out["focus_lock_nudge"] = (
                f"Still your focus for today: «{title[:100]}» — no rush; one small step is enough."
            )

    msg = guidance.get("message") or guidance.get("encouragement") or ""
    if isinstance(msg, str) and msg.strip():
        out["voice_script"] = msg.strip()[:600]

    return out
