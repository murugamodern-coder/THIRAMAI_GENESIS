"""
Simulated IoT stream for HDPE/PVC extrusion line (Digital Twin).

State persists in vault/digital_twin_state.json (not web-exposed).
If hydraulic_issue is not marked fixed, the line stays Down (red) regardless of Start.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = ROOT / "vault"
STATE_PATH = VAULT_DIR / "digital_twin_state.json"
MACHINERY_FIX_TXT = VAULT_DIR / "machinery_fix.txt"

STAGES: tuple[str, ...] = (
    "hopper",
    "extruder",
    "die",
    "cooling_tank",
    "haul_off",
    "cutter",
)

# Running setpoint (post hydraulic clear — dashboard “RUNNING” profile)
RUNNING_SCREW_RPM_TARGET = 40.0
RUNNING_PRESSURE_BAR_TARGET = 150.0
NOMINAL_KG_PER_HR = 100.0 * (RUNNING_SCREW_RPM_TARGET / 60.0)  # scale from 100 @ 60 RPM
# Max wall time credited per poll (running line) — allows catch-up if dashboard was closed ~8h.
DT_CAP_SECONDS = 8 * 3600.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t
    except ValueError:
        return None


def default_state() -> dict[str, Any]:
    return {
        "hydraulic_fixed": False,
        "operator_running": False,
        "maintenance_mode": False,
        "estimated_stock_kg": 0.0,
        "last_tick_utc": None,
        "sim_phase": 0.0,
    }


def load_state() -> dict[str, Any]:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        return default_state()
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_state()
        out = default_state()
        for k in out:
            if k in raw:
                out[k] = raw[k]
        if "hydraulic_fixed" in raw:
            out["hydraulic_fixed"] = bool(raw["hydraulic_fixed"])
        if "operator_running" in raw:
            out["operator_running"] = bool(raw["operator_running"])
        if "maintenance_mode" in raw:
            out["maintenance_mode"] = bool(raw["maintenance_mode"])
        if "estimated_stock_kg" in raw:
            try:
                out["estimated_stock_kg"] = float(raw["estimated_stock_kg"])
            except (TypeError, ValueError):
                pass
        if "sim_phase" in raw:
            try:
                out["sim_phase"] = float(raw["sim_phase"])
            except (TypeError, ValueError):
                pass
        out["last_tick_utc"] = raw.get("last_tick_utc")
        return out
    except (json.JSONDecodeError, OSError):
        return default_state()


def _append_hydraulic_fixed_to_machinery_log() -> None:
    """Mirror dashboard 'Hydraulic issue fixed' into vault/machinery_fix.txt."""
    ts = _utc_now().strftime("%Y-%m-%d %H:%M UTC")
    block = (
        f"\n\n---\n## Digital Twin — Hydraulic marked FIXED ({ts})\n\n"
        "Operator acknowledged **Hydraulic issue fixed** via dashboard control panel. "
        "Extrusion line **eligible for RUNNING**; target profile: **~150 bar** head pressure, **~40 RPM** screw (simulated).\n\n"
    )
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        existing = MACHINERY_FIX_TXT.read_text(encoding="utf-8") if MACHINERY_FIX_TXT.is_file() else ""
        MACHINERY_FIX_TXT.write_text(existing + block, encoding="utf-8")
    except OSError:
        pass


def save_state(state: dict[str, Any]) -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    to_write = {
        "hydraulic_fixed": bool(state.get("hydraulic_fixed", False)),
        "operator_running": bool(state.get("operator_running", False)),
        "maintenance_mode": bool(state.get("maintenance_mode", False)),
        "estimated_stock_kg": float(state.get("estimated_stock_kg", 0.0)),
        "last_tick_utc": state.get("last_tick_utc"),
        "sim_phase": float(state.get("sim_phase", 0.0)),
    }
    try:
        STATE_PATH.write_text(json.dumps(to_write, indent=2), encoding="utf-8")
    except OSError:
        pass


def apply_control(
    *,
    operator_running: bool | None = None,
    hydraulic_fixed: bool | None = None,
    maintenance_mode: bool | None = None,
) -> dict[str, Any]:
    """Merge control panel writes and persist (instant twin reaction on next poll)."""
    state = load_state()
    prev_h = bool(state.get("hydraulic_fixed", False))
    if operator_running is not None:
        state["operator_running"] = operator_running
    if hydraulic_fixed is not None:
        state["hydraulic_fixed"] = hydraulic_fixed
    if maintenance_mode is not None:
        state["maintenance_mode"] = maintenance_mode
    new_h = bool(state.get("hydraulic_fixed", False))
    if new_h and not prev_h:
        _append_hydraulic_fixed_to_machinery_log()
    save_state(state)
    return state


def line_mode_from_state(state: dict[str, Any]) -> str:
    """running | maintenance | down"""
    if not bool(state.get("hydraulic_fixed", False)):
        return "down"
    if bool(state.get("maintenance_mode", False)):
        return "maintenance"
    if bool(state.get("operator_running", False)):
        return "running"
    return "down"


def tick_and_get_live_status() -> dict[str, Any]:
    """
    Advance simulation by wall-clock delta, update estimated stock when Running,
    return payload for /factory/live-status.
    """
    now = _utc_now()
    state = load_state()
    last = _parse_iso(state.get("last_tick_utc")) or now
    dt = (now - last).total_seconds()
    if dt < 0:
        dt = 0.0
    dt = min(dt, DT_CAP_SECONDS)

    mode = line_mode_from_state(state)
    phase = float(state.get("sim_phase", 0.0))

    temp_c = 32.0
    pressure_bar = 0.2
    screw_rpm = 0.0
    power_kw = 0.8
    kg_hr = 0.0

    if mode == "running":
        phase += dt * 0.18
        # Stable RUNNING profile: ~40 RPM, ~150 bar with small animated ripple
        screw_rpm = RUNNING_SCREW_RPM_TARGET + 1.2 * math.sin(phase) + random.uniform(-0.35, 0.35)
        pressure_bar = RUNNING_PRESSURE_BAR_TARGET + 2.5 * math.sin(phase * 0.8) + random.uniform(-0.8, 0.8)
        temp_c = 188.0 + 5.0 * math.sin(phase * 0.55) + random.uniform(-1.5, 1.5)
        power_kw = 32.0 + 6.0 * math.sin(phase * 0.4) + random.uniform(-1.0, 1.0)
        if math.sin(phase * 1.15) > 0.985:
            temp_c = 211.0 + random.uniform(0.2, 3.0)
        kg_hr = NOMINAL_KG_PER_HR * max(0.0, screw_rpm / max(RUNNING_SCREW_RPM_TARGET, 1.0))
        stock = float(state.get("estimated_stock_kg", 0.0))
        delta_kg = kg_hr * (dt / 3600.0)
        stock += delta_kg
        state["estimated_stock_kg"] = stock
        try:
            from factory.scrap_engine import twin_tick_append_scrap

            twin_tick_append_scrap(kg_produced_delta=delta_kg, current_stock_kg=stock)
        except Exception:
            pass
    elif mode == "maintenance":
        phase += dt * 0.04
        screw_rpm = 8.0 + random.uniform(-1.0, 1.0)
        temp_c = 118.0 + random.uniform(-5.0, 5.0)
        pressure_bar = 20.0 + random.uniform(-3.0, 3.0)
        power_kw = 6.0 + random.uniform(-0.5, 0.5)
    else:
        screw_rpm = 0.0
        temp_c = 28.0 + random.uniform(-1.0, 1.5)
        pressure_bar = 0.5 + random.uniform(-0.1, 0.1)
        power_kw = 0.5 + random.uniform(0.0, 0.4)

    state["sim_phase"] = phase
    state["last_tick_utc"] = now.isoformat()
    save_state(state)

    if mode == "running":
        led = "green"
    elif mode == "maintenance":
        led = "yellow"
    else:
        led = "red"

    stages = {s: led for s in STAGES}
    critical_temp = temp_c > 210.0

    return {
        "timestamp_utc": now.isoformat(),
        "line_mode": mode,
        "stages": stages,
        "sensors": {
            "temperature_c": round(temp_c, 2),
            "pressure_bar": round(pressure_bar, 2),
            "screw_rpm": round(screw_rpm, 2),
            "power_kw": round(power_kw, 2),
        },
        "production_kg_hr": round(kg_hr, 3),
        "nominal_kg_hr": round(NOMINAL_KG_PER_HR, 3),
        "running_profile": {
            "pressure_bar_target": RUNNING_PRESSURE_BAR_TARGET,
            "screw_rpm_target": RUNNING_SCREW_RPM_TARGET,
        },
        "estimated_stock_kg": round(float(state.get("estimated_stock_kg", 0.0)), 4),
        "critical_temperature": critical_temp,
        "hydraulic_fixed": bool(state.get("hydraulic_fixed", False)),
        "operator_running": bool(state.get("operator_running", False)),
        "maintenance_mode": bool(state.get("maintenance_mode", False)),
        "hydraulic_gate_reason": (
            None
            if bool(state.get("hydraulic_fixed", False))
            else "Hydraulic issue not marked Fixed — line locked Down (simulated)."
        ),
    }


def read_estimated_stock_kg() -> float:
    """Light read for financial summary (no simulation tick)."""
    try:
        return float(load_state().get("estimated_stock_kg", 0.0))
    except (TypeError, ValueError):
        return 0.0
