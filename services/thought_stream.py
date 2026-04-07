"""
JARVIS UI bridge: append-only **thought stream** for ``/logs/thought_stream.json``.

The orchestrator (and optional workers) write short, human-readable debate lines so operators can
watch internal reasoning on ``/dashboard/live``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_LOGS = _ROOT / "logs"
_STREAM_PATH = _LOGS / "thought_stream.json"
_MAX_ENTRIES = int((os.getenv("THIRAMAI_THOUGHT_STREAM_MAX") or "400").strip() or "400")
_MESSAGE_MAX = max(500, min(32_000, int((os.getenv("THIRAMAI_THOUGHT_STREAM_MESSAGE_MAX") or "16000").strip() or "16000")))
_lock = threading.Lock()


def thought_stream_enabled() -> bool:
    return not (os.getenv("THIRAMAI_THOUGHT_STREAM_DISABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _ensure_logs() -> None:
    _LOGS.mkdir(parents=True, exist_ok=True)


def _load_unlocked() -> dict[str, Any]:
    if not _STREAM_PATH.is_file():
        return {"thoughts": [], "updated_at": None}
    try:
        data = json.loads(_STREAM_PATH.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return {"thoughts": [], "updated_at": None}
        thoughts = data.get("thoughts")
        if not isinstance(thoughts, list):
            thoughts = []
        return {"thoughts": thoughts, "updated_at": data.get("updated_at")}
    except (OSError, json.JSONDecodeError, TypeError):
        return {"thoughts": [], "updated_at": None, "recover_note": "rebuilt_after_corrupt_file"}


def read_thought_stream() -> dict[str, Any]:
    """Return the current stream (newest entries last in ``thoughts``)."""
    with _lock:
        data = _load_unlocked()
        data.setdefault("schema", "jarvis_thought_stream_v1")
        return data


def clear_thought_stream() -> dict[str, Any]:
    """Reset the thought stream file to an empty list (dashboard \"clear cache\")."""
    _ensure_logs()
    out: dict[str, Any] = {
        "schema": "jarvis_thought_stream_v1",
        "updated_at": time.time(),
        "thoughts": [],
        "cleared": True,
        "ok": True,
    }
    with _lock:
        tmp = _STREAM_PATH.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(_STREAM_PATH)
        except OSError:
            try:
                if tmp.is_file():
                    tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
            except OSError:
                pass
            return {
                "schema": "jarvis_thought_stream_v1",
                "thoughts": [],
                "cleared": False,
                "ok": False,
                "error": "could_not_write_thought_stream",
            }
    return out


def append_thought(
    message: str,
    *,
    phase: str = "think",
    agent: str = "orchestrator",
    request_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append one line to the JSON stream (atomic replace, capped list)."""
    if not thought_stream_enabled():
        return
    msg = (message or "").strip()
    if not msg:
        return
    _ensure_logs()
    entry: dict[str, Any] = {
        "ts": time.time(),
        "phase": (phase or "think")[:128],
        "agent": (agent or "orchestrator")[:128],
        "message": msg[:_MESSAGE_MAX],
    }
    if request_id:
        entry["request_id"] = str(request_id)[:64]
    if meta:
        entry["meta"] = {k: v for k, v in list(meta.items())[:16]}

    with _lock:
        data = _load_unlocked()
        thoughts: list[Any] = list(data.get("thoughts") or [])
        thoughts.append(entry)
        cap = max(10, min(_MAX_ENTRIES, 5000))
        if len(thoughts) > cap:
            thoughts = thoughts[-cap:]
        out = {
            "schema": "jarvis_thought_stream_v1",
            "updated_at": time.time(),
            "thoughts": thoughts,
        }
        tmp = _STREAM_PATH.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(_STREAM_PATH)
        except OSError:
            try:
                if tmp.is_file():
                    tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
            except OSError:
                pass


def append_exception_thought(
    exc: BaseException,
    *,
    prefix: str = "",
    phase: str = "error",
    agent: str = "system",
    request_id: str | None = None,
    with_traceback: bool = False,
) -> None:
    """
    Log the **full** exception string (and optional traceback) to the thought stream — not just the type name.
    """
    body = f"{type(exc).__name__}: {exc}"
    if with_traceback:
        tb = traceback.format_exc()
        if tb and tb.strip():
            body = body + "\n\n" + tb.strip()
    if prefix:
        body = f"{prefix.strip()}\n\n{body}"
    append_thought(body, phase=phase, agent=agent, request_id=request_id)
