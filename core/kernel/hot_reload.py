"""Persisted signal: sandbox pytest passed → orchestrator should observe and operators may restart."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
_REDIS_KEY = "thiramai:kernel:hot_reload_pending"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_path() -> Path:
    p = _repo_root() / "var" / "kernel" / "hot_reload_pending.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _redis_client():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis

        return redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0)
    except Exception:
        return None


def publish_hot_reload(*, patch_relative_path: str, pytest_exit_code: int, log_tail: str = "") -> None:
    payload: dict[str, Any] = {
        "patch_relative_path": patch_relative_path,
        "pytest_exit_code": int(pytest_exit_code),
        "ts": time.time(),
        "log_tail": (log_tail or "")[-8000:],
    }
    raw = json.dumps(payload, ensure_ascii=False)
    r = _redis_client()
    if r is not None:
        try:
            r.set(_REDIS_KEY, raw)
        except Exception:
            pass
    _file_path().write_text(raw, encoding="utf-8")

    _cicd_hot = (
        os.getenv("THIRAMAI_CI_CD_ON_HOT_RELOAD") or os.getenv("THIRAMAI_CICD_ON_HOT_RELOAD") or ""
    ).strip().lower()
    if _cicd_hot in ("1", "true", "yes", "on"):
        try:
            from services import ci_cd_trigger

            result = ci_cd_trigger.trigger_after_sandbox_approval(
                patch_relative_path=str(payload["patch_relative_path"]),
                pytest_exit_code=int(payload["pytest_exit_code"]),
                source="hot_reload",
                extra={"ts": payload.get("ts"), "log_tail": (payload.get("log_tail") or "")[:4000]},
            )
            if not result.get("ok"):
                _log.warning("hot_reload: ci_cd_trigger failed %s", result.get("detail"))
        except Exception as exc:
            _log.warning("hot_reload: ci_cd_trigger exception %s", exc)


def peek_pending() -> dict[str, Any] | None:
    r = _redis_client()
    if r is not None:
        try:
            raw = r.get(_REDIS_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    fp = _file_path()
    if fp.is_file():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def clear_pending() -> None:
    r = _redis_client()
    if r is not None:
        try:
            r.delete(_REDIS_KEY)
        except Exception:
            pass
    fp = _file_path()
    if fp.is_file():
        try:
            fp.unlink()
        except OSError:
            pass
