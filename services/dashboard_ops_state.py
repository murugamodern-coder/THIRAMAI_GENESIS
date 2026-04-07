"""
Operator-controlled dashboard state (persists under ``var/``).

Predictive scaling **manual** mode disables calendar/memory threshold drops while the API server
process is running; state survives restarts via ``var/predictive_scaling_mode``.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VAR = _ROOT / "var"
_MODE_FILE = _VAR / "predictive_scaling_mode"
_INFRA_BUDGET_OVERRIDE = _VAR / "operational_infra_budget_inr_override"


def get_predictive_scaling_mode() -> str:
    """
    ``ai`` — allow ``predictive_autoscale_threshold_adjustment`` as usual.
    ``manual`` — no predictive drop; effective threshold equals learned/base path only.
    """
    if not _MODE_FILE.is_file():
        return "ai"
    raw = _MODE_FILE.read_text(encoding="utf-8", errors="replace").strip().lower()
    if raw in ("manual", "off", "0", "false"):
        return "manual"
    return "ai"


def set_predictive_scaling_mode(mode: str) -> str:
    """Persist ``ai`` or ``manual``; returns normalized mode."""
    normalized = "manual" if str(mode).strip().lower() in ("manual", "off", "0", "false") else "ai"
    _VAR.mkdir(parents=True, exist_ok=True)
    _MODE_FILE.write_text(normalized + "\n", encoding="utf-8")
    return normalized


def get_operational_infra_budget_inr_override() -> str | None:
    """
    Optional monthly INR cap persisted under ``var/`` (operator console / NL command).

    When set, ``economics_service.infra_scaling_budget_check`` prefers this over
    ``THIRAMAI_OPERATIONAL_INFRA_BUDGET_INR`` until cleared.
    """
    if not _INFRA_BUDGET_OVERRIDE.is_file():
        return None
    raw = _INFRA_BUDGET_OVERRIDE.read_text(encoding="utf-8", errors="replace").strip()
    return raw or None


def set_operational_infra_budget_inr_override(amount_inr: str) -> str:
    """Persist cap as a decimal string (e.g. ``1000`` or ``1000.00``)."""
    s = str(amount_inr or "").strip()
    if not s:
        raise ValueError("budget_amount_required")
    _VAR.mkdir(parents=True, exist_ok=True)
    _INFRA_BUDGET_OVERRIDE.write_text(s + "\n", encoding="utf-8")
    return s


def clear_operational_infra_budget_inr_override() -> bool:
    """Remove file override; economics falls back to env only."""
    try:
        if _INFRA_BUDGET_OVERRIDE.is_file():
            _INFRA_BUDGET_OVERRIDE.unlink()
            return True
    except OSError:
        pass
    return False
