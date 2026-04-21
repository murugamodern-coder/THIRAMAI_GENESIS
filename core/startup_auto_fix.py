"""
Best-effort repairs before binding the ASGI server (rebuild Command Center, env hints).

All actions are opt-in or bounded by timeouts so production hosts stay predictable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.stability.failure_memory import FailureMemory
from core.stability.logging_tags import log_stability
from core.startup_checks import StartupReport, log_line


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _truthy(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def rebuild_command_center(root: Path | None = None) -> tuple[bool, str]:
    """
    Run ``npm ci`` + ``npm run build`` in ``web/command_center`` (Windows-friendly via shell).
    """
    root = root or _repo_root()
    cc = root / "web" / "command_center"
    if not (cc / "package.json").is_file():
        return False, f"missing {cc / 'package.json'}"

    max_sec = int(os.environ.get("THIRAMAI_STARTUP_BUILD_TIMEOUT_SEC", "300") or "300")
    log_line("AUTO FIX TRIGGERED", f"npm ci + npm run build in {cc} (timeout {max_sec}s)")

    npm = shutil.which("npm")
    if not npm:
        return False, "npm not found on PATH"

    try:
        subprocess.run(
            [npm, "ci"],
            cwd=str(cc),
            check=True,
            timeout=max_sec,
            shell=False,
        )
        subprocess.run(
            [npm, "run", "build"],
            cwd=str(cc),
            check=True,
            timeout=max_sec,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"build timed out after {max_sec}s"
    except subprocess.CalledProcessError as e:
        return False, f"npm failed: {e}"

    return True, "command_center rebuilt"


def run_restart_command() -> tuple[bool, str]:
    """Optional ``THIRAMAI_STARTUP_RESTART_CMD`` — shell one-liner to restart a supervisor."""
    cmd = (os.environ.get("THIRAMAI_STARTUP_RESTART_CMD") or "").strip()
    if not cmd:
        return True, "no THIRAMAI_STARTUP_RESTART_CMD set"
    log_line("AUTO FIX TRIGGERED", f"THIRAMAI_STARTUP_RESTART_CMD: {cmd[:120]}")
    try:
        subprocess.run(cmd, shell=True, check=False, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "restart command timed out"
    return True, "restart command executed"


def apply_auto_fixes(
    report: StartupReport,
    *,
    root: Path | None = None,
    failure_memory: FailureMemory | None = None,
) -> list[str]:
    """
    Apply fixes for failed checks. Returns human-readable actions.

    Controlled by ``THIRAMAI_STARTUP_AUTO_BUILD`` (default **on** when unset).
    """
    root = root or _repo_root()
    actions: list[str] = []
    if report.ok:
        return actions

    auto_build = _truthy("THIRAMAI_STARTUP_AUTO_BUILD", default=True)
    names = {i.name for i in report.items if not i.ok}

    if failure_memory:
        for n in list(names):
            if failure_memory.strategy_for("startup", n) == "skip":
                log_stability(f"auto-fix skipped for {n} (failure memory: skip)")
                names.discard(n)

    if auto_build and names & {"command_center_index", "bundle_integrity"}:
        ok, msg = rebuild_command_center(root)
        actions.append(f"rebuild_command_center: {msg}")
        if not ok:
            log_line("AUTO FIX", f"rebuild failed: {msg}")

    # If something else is listening but unhealthy, optional external restart (ops hook).
    if "api_health" in names and _truthy("THIRAMAI_STARTUP_RESTART_ON_API_FAIL", default=False):
        ok, msg = run_restart_command()
        actions.append(f"restart_cmd: {msg}")
        if not ok:
            log_line("AUTO FIX", f"restart failed: {msg}")

    time.sleep(float(os.environ.get("THIRAMAI_STARTUP_RECHECK_DELAY_SEC", "0.2") or "0.2"))
    return actions


def enable_safe_start_env(reason: str) -> None:
    """Set process env for degraded / incident-style server behavior (before ``import app``)."""
    os.environ["THIRAMAI_INCIDENT_MODE"] = "1"
    os.environ["THIRAMAI_STARTUP_DEGRADED"] = "1"
    if not (os.environ.get("THIRAMAI_SAFE_ERRORS") or "").strip():
        os.environ["THIRAMAI_SAFE_ERRORS"] = "1"
    log_line("AUTO FIX TRIGGERED", f"safe / incident env enabled: {reason}")
