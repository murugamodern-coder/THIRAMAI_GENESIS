"""
Background driver for ``run_autonomous_cycle`` — **disabled unless** ``THIRAMAI_AUTONOMOUS_MODE=1``.

Run standalone::

    python -m core.autonomous_scheduler

Uses ``THIRAMAI_AUTONOMOUS_INTERVAL_SEC`` (default 60) between cycles.
"""

from __future__ import annotations

import os
import time
from typing import Any

from core.autonomous_loop import autonomous_mode_enabled, run_autonomous_cycle
from core.observability import ensure_thiramai_logging, log_event, new_request_id


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> int:
    raw = (os.getenv("THIRAMAI_AUTONOMOUS_INTERVAL_SEC") or "60").strip()
    try:
        return max(15, min(86_400, int(raw)))
    except ValueError:
        return 60


def _organization_ids() -> list[int]:
    raw = (os.getenv("THIRAMAI_AUTONOMOUS_ORG_IDS") or "").strip()
    if raw:
        out: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                out.append(int(part))
        return out
    single = (os.getenv("THIRAMAI_AUTONOMOUS_ORG_ID") or os.getenv("THIRAMAI_DEFAULT_ORG_ID") or "0").strip()
    try:
        v = int(single)
    except ValueError:
        v = 0
    return [v] if v > 0 else []


def _auto_execute_flag() -> bool:
    return _truthy("THIRAMAI_AUTONOMOUS_EXEC") or _truthy("THIRAMAI_ORCHESTRATOR_AUTO_MODE")


def _base_context(organization_id: int) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "organization_id": int(organization_id),
        "auto_mode": _auto_execute_flag(),
        "actor_role_name": (os.getenv("THIRAMAI_AUTONOMOUS_ACTOR_ROLE") or "owner").strip().lower(),
        "correlation_id": None,
    }
    uid_raw = (os.getenv("THIRAMAI_AUTONOMOUS_USER_ID") or "").strip()
    if uid_raw.isdigit():
        ctx["user_id"] = int(uid_raw)
    rl_raw = (os.getenv("THIRAMAI_AUTONOMOUS_ROLE_LEVEL") or "").strip()
    if rl_raw.isdigit():
        ctx["role_level"] = int(rl_raw)
    return ctx


def run_autonomous_loop() -> None:
    """
    Infinite loop: one cycle per configured org per iteration, then sleep.

    Respects ``THIRAMAI_AUTONOMOUS_MODE`` — if off, logs once and returns without looping.
    """
    ensure_thiramai_logging()
    rid = new_request_id()
    if not autonomous_mode_enabled():
        log_event(
            rid,
            "autonomous_scheduler.disabled",
            ok=True,
            extra={"hint": "Set THIRAMAI_AUTONOMOUS_MODE=1 to enable"},
        )
        return

    orgs = _organization_ids()
    if not orgs:
        log_event(
            rid,
            "autonomous_scheduler.no_orgs",
            ok=False,
            extra={"hint": "Set THIRAMAI_AUTONOMOUS_ORG_ID or THIRAMAI_AUTONOMOUS_ORG_IDS"},
        )
        return

    interval = _interval_sec()
    log_event(
        new_request_id(),
        "autonomous_scheduler.started",
        ok=True,
        extra={"organizations": orgs, "interval_sec": interval, "auto_execute": _auto_execute_flag()},
    )

    try:
        while True:
            tick = new_request_id()
            for oid in orgs:
                try:
                    run_autonomous_cycle(_base_context(oid))
                except Exception as exc:
                    log_event(
                        tick,
                        "autonomous_scheduler.cycle_failed",
                        ok=False,
                        error=f"{type(exc).__name__}: {exc}",
                        extra={"organization_id": oid},
                    )
            try:
                from services.worker_heartbeat import touch_heartbeat

                touch_heartbeat("autonomous_loop")
            except Exception:
                pass
            time.sleep(interval)
    except KeyboardInterrupt:
        log_event(new_request_id(), "autonomous_scheduler.stopped", ok=True, extra={"reason": "keyboard"})


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(".") / ".env", override=True)
    run_autonomous_loop()
