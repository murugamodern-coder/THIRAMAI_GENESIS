"""Startup validation for THIRAMAI environment (phase 58 — fail-fast)."""

from __future__ import annotations

import os


def validate_thiramai_environment(*, raise_on_error: bool = True) -> list[str]:
    """
    Validate numeric ranges and critical combinations after ``thiramai.config`` is loaded.

    Returns a list of error strings (empty if ok). Raises ``RuntimeError`` if ``raise_on_error``
    and any error exists.
    """
    from thiramai import config as cfg

    errs: list[str] = []

    raw_goal_max = (os.getenv("THIRAMAI_GOAL_MAX_SECONDS") or "").strip()
    if raw_goal_max:
        try:
            gm = int(raw_goal_max)
            if gm < 30 or gm > 86400:
                errs.append("THIRAMAI_GOAL_MAX_SECONDS must be between 30 and 86400")
        except ValueError:
            errs.append("THIRAMAI_GOAL_MAX_SECONDS must be an integer")

    raw_conc = (os.getenv("THIRAMAI_MAX_CONCURRENT_GOAL_JOBS") or "").strip()
    if raw_conc:
        try:
            c = int(raw_conc)
            if c < 1 or c > 64:
                errs.append("THIRAMAI_MAX_CONCURRENT_GOAL_JOBS must be between 1 and 64")
        except ValueError:
            errs.append("THIRAMAI_MAX_CONCURRENT_GOAL_JOBS must be an integer")

    if cfg.THIRAMAI_WORKER_POLL_SEC > 3600:
        errs.append("THIRAMAI_WORKER_POLL_SEC unreasonably large (>3600)")

    mode = str(os.getenv("THIRAMAI_MODE") or "").strip().lower()
    if mode and mode not in ("dry_run", "dry-run", "dryrun", "simulation", "live"):
        errs.append("THIRAMAI_MODE must be one of: dry-run, simulation, live")

    if raise_on_error and errs:
        raise RuntimeError("Invalid THIRAMAI configuration:\n- " + "\n- ".join(errs))
    return errs
