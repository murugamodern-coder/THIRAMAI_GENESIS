#!/usr/bin/env python3
"""
THIRAMAI Genesis — safe process entrypoint.

Flow: load env → pre-bind checks → optional auto-fix → recheck → optional API probe
→ set degraded/incident env if needed → start uvicorn (never exits on validation alone
unless ``--strict`` is passed).

Usage::

    python run_system.py
    python run_system.py --strict          # exit non-zero if pre-bind checks fail
    python run_system.py --probe-api       # require /health/* on base URL before bind
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv_early() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=ROOT / ".env", override=False)
    except ImportError:
        pass


def _parse_required_env(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _default_api_base() -> str:
    port = (os.environ.get("THIRAMAI_PORT") or os.environ.get("PORT") or "8000").strip() or "8000"
    return f"http://127.0.0.1:{port}"


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_early()

    parser = argparse.ArgumentParser(description="THIRAMAI safe startup + ASGI server")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 if pre-bind validation fails (after auto-fix).",
    )
    parser.add_argument(
        "--probe-api",
        action="store_true",
        help="Before bind, require GET /health/live and /health/ready on THIRAMAI_STARTUP_API_BASE.",
    )
    parser.add_argument(
        "--no-auto-build",
        action="store_true",
        help="Disable npm rebuild auto-fix (sets THIRAMAI_STARTUP_AUTO_BUILD=0 for this process).",
    )
    args = parser.parse_args(argv)

    if args.no_auto_build:
        os.environ["THIRAMAI_STARTUP_AUTO_BUILD"] = "0"

    from core.stability.auto_fix_guard import AutoFixGuard
    from core.stability.escalation import maybe_escalate_incident_mode
    from core.stability.failure_memory import get_failure_memory
    from core.startup_auto_fix import apply_auto_fixes, enable_safe_start_env
    from core.startup_checks import _parse_port, log_line, run_startup_checks, tcp_open

    required = _parse_required_env(os.environ.get("THIRAMAI_STARTUP_REQUIRED_ENV"))
    probe_base = None
    if args.probe_api or _truthy_env("THIRAMAI_STARTUP_PROBE_API"):
        probe_base = (os.environ.get("THIRAMAI_STARTUP_API_BASE") or _default_api_base()).rstrip("/")

    max_fix_rounds = int(os.environ.get("THIRAMAI_STARTUP_FIX_ROUNDS", "2") or "2")
    fix_cooldown = float(os.environ.get("THIRAMAI_AUTO_FIX_COOLDOWN_SEC", "2") or "2")
    fix_cooldown = max(0.0, fix_cooldown)

    log_line("STARTUP CHECK", f"repo={ROOT}")

    guard = AutoFixGuard()
    fm = get_failure_memory()
    report = run_startup_checks(root=ROOT, probe_api_base=probe_base, required_env=required or None)
    rounds = 0
    while not report.ok and rounds < max_fix_rounds:
        failed = set(report.failed_names())
        if not failed:
            break
        if not guard.can_attempt(failed):
            break
        if rounds > 0:
            time.sleep(fix_cooldown)
        guard.record_attempt(failed)
        for name in failed:
            detail = next((i.detail for i in report.items if i.name == name), "")
            fm.record("startup", name, detail)
        actions = apply_auto_fixes(report, root=ROOT, failure_memory=fm)
        if actions:
            for a in actions:
                log_line("AUTO FIX TRIGGERED", a)
        rounds += 1
        report = run_startup_checks(root=ROOT, probe_api_base=probe_base, required_env=required or None)

    if not report.ok:
        max_c = max((fm.get_count("startup", n) for n in report.failed_names()), default=0)
        maybe_escalate_incident_mode(failure_count=max_c, reason="persistent startup failures")
        for n in report.failed_names():
            if fm.strategy_for("startup", n) == "degrade":
                maybe_escalate_incident_mode(unstable=True, reason=f"failure memory degrade: {n}")
                break
        enable_safe_start_env("pre-bind checks failed: " + ", ".join(report.failed_names()))
        log_line("STARTUP CHECK", "degraded mode — server will still start")

    # Optional: port already in use and healthy → exit without double-binding
    if _truthy_env("THIRAMAI_STARTUP_EXIT_IF_HEALTHY_PORT"):
        port = _parse_port(os.environ.get("THIRAMAI_PORT") or os.environ.get("PORT"))
        if tcp_open("127.0.0.1", port):
            probe = (os.environ.get("THIRAMAI_STARTUP_API_BASE") or _default_api_base()).rstrip("/")
            r2 = run_startup_checks(root=ROOT, probe_api_base=probe, required_env=required or None)
            if r2.ok:
                log_line("SYSTEM READY", f"port {port} already serves healthy API — exiting 0")
                return 0

    if not report.ok and args.strict:
        log_line("STARTUP CHECK", "FAILED (--strict)")
        return 2

    log_line("SYSTEM READY", "starting ASGI server")
    import uvicorn

    bind_host = (os.environ.get("THIRAMAI_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    bind_port = _parse_port(os.environ.get("THIRAMAI_PORT") or os.environ.get("PORT"))
    reload = (os.environ.get("THIRAMAI_UVICORN_RELOAD", "").strip().lower() in ("1", "true", "yes", "on"))

    uvicorn.run(
        "main:app",
        host=bind_host,
        port=bind_port,
        reload=reload,
    )
    return 0


def _truthy_env(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


if __name__ == "__main__":
    raise SystemExit(main())
