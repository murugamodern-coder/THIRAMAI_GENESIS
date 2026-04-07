"""
THIRAMAI Factory — Scrap intelligence (Phase 9).

**HQRS** — *High-Quality Robotics Scrap*: **2%** of production mass when the Digital Twin
line is **RUNNING** (~**100 kg/hr** nominal), modelled as usable **HDPE** for 3D printing.

Persists to **vault/rd_core/scrap_inventory.json** with canonical fields
``total_scrap_kg`` and ``last_updated`` (calendar date), plus internal run history.

From project root:
    python factory/scrap_engine.py
    python factory/scrap_engine.py --sync-twin
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RD_CORE = ROOT / "vault" / "rd_core"
SCRAP_INVENTORY_PATH = RD_CORE / "scrap_inventory.json"

USABLE_SCRAP_FRACTION = 0.02
NOMINAL_KG_HR_REF = 100.0
MAX_RUN_ENTRIES = 200


def default_inventory() -> dict[str, Any]:
    return {
        "total_scrap_kg": 0.0,
        "last_updated": date.today().isoformat(),
        "high_quality_scrap_kg": 0.0,
        "usable_scrap_fraction": USABLE_SCRAP_FRACTION,
        "nominal_kg_hr_ref": NOMINAL_KG_HR_REF,
        "last_logged_stock_kg": None,
        "runs": [],
        "last_updated_utc": None,
    }


def _sync_hqrs_public_fields(inv: dict[str, Any]) -> None:
    """Keep HQRS totals aligned for R&D dashboards and spec JSON."""
    try:
        hq = float(inv.get("high_quality_scrap_kg", inv.get("total_scrap_kg", 0.0)))
    except (TypeError, ValueError):
        hq = 0.0
    inv["high_quality_scrap_kg"] = round(hq, 6)
    inv["total_scrap_kg"] = round(hq, 6)
    inv["last_updated"] = date.today().isoformat()


def load_inventory() -> dict[str, Any]:
    RD_CORE.mkdir(parents=True, exist_ok=True)
    if not SCRAP_INVENTORY_PATH.is_file():
        return default_inventory()
    try:
        raw = json.loads(SCRAP_INVENTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_inventory()
        out = default_inventory()
        for k in ("high_quality_scrap_kg", "usable_scrap_fraction", "nominal_kg_hr_ref", "last_logged_stock_kg"):
            if k in raw:
                out[k] = raw[k]
        if "total_scrap_kg" in raw and "high_quality_scrap_kg" not in raw:
            try:
                out["high_quality_scrap_kg"] = float(raw["total_scrap_kg"])
            except (TypeError, ValueError):
                pass
        if isinstance(raw.get("runs"), list):
            out["runs"] = raw["runs"][-MAX_RUN_ENTRIES:]
        if raw.get("last_updated_utc"):
            out["last_updated_utc"] = raw["last_updated_utc"]
        if raw.get("last_updated"):
            out["last_updated"] = str(raw["last_updated"])
        try:
            out["high_quality_scrap_kg"] = float(out["high_quality_scrap_kg"])
        except (TypeError, ValueError):
            out["high_quality_scrap_kg"] = 0.0
        _sync_hqrs_public_fields(out)
        return out
    except (json.JSONDecodeError, OSError):
        return default_inventory()


def save_inventory(data: dict[str, Any]) -> None:
    RD_CORE.mkdir(parents=True, exist_ok=True)
    _sync_hqrs_public_fields(data)
    SCRAP_INVENTORY_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def estimate_high_quality_scrap_kg(*, kg_produced: float, fraction: float | None = None) -> float:
    """2% (default) of production mass → print-grade scrap estimate."""
    f = USABLE_SCRAP_FRACTION if fraction is None else float(fraction)
    if kg_produced <= 0:
        return 0.0
    return round(kg_produced * f, 6)


def append_production_run(
    *,
    kg_produced: float,
    source: str = "manual",
    note: str = "",
    fraction: float | None = None,
) -> dict[str, Any]:
    """
    Add scrap from a single production increment and persist vault JSON.
    """
    inv = load_inventory()
    scrap = estimate_high_quality_scrap_kg(kg_produced=kg_produced, fraction=fraction)
    if scrap <= 0:
        inv["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        save_inventory(inv)
        return inv

    inv["high_quality_scrap_kg"] = round(float(inv["high_quality_scrap_kg"]) + scrap, 6)
    entry = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "kg_produced": round(kg_produced, 6),
        "high_quality_scrap_kg": scrap,
        "source": source,
        "note": note,
    }
    runs = inv.get("runs") if isinstance(inv.get("runs"), list) else []
    runs.append(entry)
    inv["runs"] = runs[-MAX_RUN_ENTRIES:]
    inv["last_updated_utc"] = entry["ts_utc"]
    save_inventory(inv)
    return inv


def sync_from_digital_twin() -> dict[str, Any]:
    """
    Credit scrap from **new** production since last sync (estimated_stock_kg delta).
    """
    from factory.machine_sensor import load_state

    inv = load_inventory()
    state = load_state()
    stock = float(state.get("estimated_stock_kg", 0.0))
    prev = inv.get("last_logged_stock_kg")
    if prev is None:
        inv["last_logged_stock_kg"] = stock
        inv["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        save_inventory(inv)
        return inv
    try:
        prev_f = float(prev)
    except (TypeError, ValueError):
        prev_f = 0.0
    delta = max(0.0, stock - prev_f)
    inv["last_logged_stock_kg"] = stock
    if delta > 1e-9:
        inv = append_production_run(
            kg_produced=delta,
            source="digital_twin_delta",
            note="sync_from_digital_twin",
        )
    else:
        inv["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        save_inventory(inv)
    return inv


def deduct_for_fabrication(
    *,
    kg: float,
    part_id: str,
    note: str = "",
) -> dict[str, Any]:
    """
    Consume HQRS for an R&D print job. Returns ``ok: False`` if vault mass is insufficient
    (no partial deduct). Logs a run entry with ``source: fabrication``.
    """
    inv = load_inventory()
    have = float(inv.get("high_quality_scrap_kg") or inv.get("total_scrap_kg") or 0.0)
    need = float(kg)
    if need <= 1e-12:
        return {
            "ok": True,
            "deducted_kg": 0.0,
            "remaining_kg": round(have, 6),
            "part_id": part_id,
            "reason": "zero_mass",
        }
    if have + 1e-9 < need:
        return {
            "ok": False,
            "deducted_kg": 0.0,
            "remaining_kg": round(have, 6),
            "shortfall_kg": round(need - have, 6),
            "needed_kg": round(need, 6),
            "part_id": part_id,
            "reason": "insufficient_hqrs",
        }

    inv["high_quality_scrap_kg"] = round(have - need, 6)
    ts = datetime.now(timezone.utc).isoformat()
    entry = {
        "ts_utc": ts,
        "fabrication_consumed_kg": round(need, 6),
        "part_id": part_id,
        "source": "fabrication",
        "note": note or "deduct_for_fabrication",
    }
    runs = inv.get("runs") if isinstance(inv.get("runs"), list) else []
    runs.append(entry)
    inv["runs"] = runs[-MAX_RUN_ENTRIES:]
    inv["last_updated_utc"] = ts
    save_inventory(inv)
    return {
        "ok": True,
        "deducted_kg": round(need, 6),
        "remaining_kg": float(inv["high_quality_scrap_kg"]),
        "part_id": part_id,
        "reason": "deducted",
    }


def twin_tick_append_scrap(*, kg_produced_delta: float, current_stock_kg: float) -> None:
    """
    Hook for live twin ticks — keeps `last_logged_stock_kg` aligned so CLI `--sync-twin`
    does not double-count after live production.
    """
    if kg_produced_delta <= 1e-12:
        return
    try:
        inv = load_inventory()
        scrap = estimate_high_quality_scrap_kg(kg_produced=kg_produced_delta)
        if scrap <= 0:
            return
        inv["high_quality_scrap_kg"] = round(float(inv["high_quality_scrap_kg"]) + scrap, 6)
        inv["last_logged_stock_kg"] = float(current_stock_kg)
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "kg_produced": round(kg_produced_delta, 6),
            "high_quality_scrap_kg": scrap,
            "source": "twin_tick",
            "note": "running_line_dt_slice",
        }
        runs = inv.get("runs") if isinstance(inv.get("runs"), list) else []
        runs.append(entry)
        inv["runs"] = runs[-MAX_RUN_ENTRIES:]
        inv["last_updated_utc"] = entry["ts_utc"]
        save_inventory(inv)
    except OSError:
        pass


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Scrap inventory — THIRAMAI R&D")
    p.add_argument(
        "--sync-twin",
        action="store_true",
        help="Credit scrap from digital twin stock delta since last run.",
    )
    p.add_argument(
        "--demo-kg",
        type=float,
        default=0.0,
        help="Append one synthetic run with this many kg produced (for testing).",
    )
    args = p.parse_args()
    if args.sync_twin:
        inv = sync_from_digital_twin()
        print("SCRAP_SYNC_OK", SCRAP_INVENTORY_PATH)
        print("total_scrap_kg:", inv.get("total_scrap_kg"), "last_updated:", inv.get("last_updated"))
        return
    if args.demo_kg > 0:
        inv = append_production_run(kg_produced=args.demo_kg, source="cli_demo", note="--demo-kg")
        print("SCRAP_APPEND_OK total_scrap_kg=", inv.get("total_scrap_kg"))
        return
    inv = load_inventory()
    print("scrap_inventory:", SCRAP_INVENTORY_PATH)
    print(json.dumps(inv, indent=2))


if __name__ == "__main__":
    main()
