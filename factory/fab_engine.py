"""
THIRAMAI Factory — R&D fabrication core (Phase 10).

Simulated **G-code manifest** for **Bushing-Joint V1** (see `vault/rd_core/humanoid_design_v1.md` §A),
print time / PE100 mass / nozzle **215 °C**, and queue state in **`vault/rd_core/fab_queue.json`**.

Deducts filament mass from **HQRS** via `scrap_engine.deduct_for_fabrication` when a job is enqueued.

    python factory/fab_engine.py
    python factory/fab_engine.py --dry-run
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RD_CORE = ROOT / "vault" / "rd_core"
FAB_QUEUE_PATH = RD_CORE / "fab_queue.json"

PART_ID = "bushing_joint_v1"
NOZZLE_C = 215
BED_C = 98
LAYER_MM = 0.2
ESTIMATED_PE100_KG = 0.022
SIMULATED_PRINT_PROGRESS_PCT = 42


def default_fab_queue() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_utc": None,
        "material_shortage": {
            "active": False,
            "needed_kg": 0.0,
            "available_kg": 0.0,
            "part_id": "",
        },
        "active_job": None,
        "history": [],
        "last_manifest_summary": None,
        "last_gcode_manifest": None,
    }


def load_fab_queue() -> dict[str, Any]:
    RD_CORE.mkdir(parents=True, exist_ok=True)
    if not FAB_QUEUE_PATH.is_file():
        return default_fab_queue()
    try:
        raw = json.loads(FAB_QUEUE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_fab_queue()
        out = default_fab_queue()
        for k in ("version", "updated_utc", "active_job", "last_manifest_summary", "last_gcode_manifest"):
            if k in raw:
                out[k] = raw[k]
        if isinstance(raw.get("material_shortage"), dict):
            out["material_shortage"].update(raw["material_shortage"])
        if isinstance(raw.get("history"), list):
            out["history"] = raw["history"][-40:]
        return out
    except (json.JSONDecodeError, OSError):
        return default_fab_queue()


def save_fab_queue(data: dict[str, Any]) -> None:
    RD_CORE.mkdir(parents=True, exist_ok=True)
    data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    FAB_QUEUE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _estimate_print_minutes(*, mass_kg: float, layer_mm: float) -> int:
    """Illustrative FDM schedule from mass + layer height (planning only)."""
    base = 28
    return int(base + mass_kg * 2200 + (0.2 / max(layer_mm, 0.05)) * 8)


def build_gcode_manifest_bushing_joint_v1() -> dict[str, Any]:
    """
    Pseudo G-code for a single bushing-joint print (PE100 @ 215 °C).
    """
    lines: list[str] = [
        "; THIRAMAI FAB — Bushing-Joint V1 (simulated)",
        f"; PE100 nozzle={NOZZLE_C}C bed={BED_C}C layer={LAYER_MM}mm",
        "G21 ; mm",
        "G90 ; absolute",
        "M104 S215 ; set hotend PE100",
        f"M140 S{BED_C} ; bed",
        "G28 ; home all",
        "G1 Z5 F3000",
        "; --- skirt / prime ---",
        "G1 X10 Y10 Z0.2 F4200 E0",
        "G1 X40 Y10 E2.5 F1800",
        "; --- perimeters (excerpt) ---",
        "G1 X40 Y40 E5.0 F1200",
        "G1 X10 Y40 E7.5 F1200",
        "G1 X10 Y10 E10.0 F1200",
        "; --- Z hop + layer change (representative) ---",
        "G1 Z0.4 F600",
        "G1 X12 Y12 F4200",
        "G1 X38 Y38 E14 F1200",
        "; ... internal sparse infill segments omitted in sim ...",
        "G1 Z12.0 F600",
        "; --- flange outline ---",
        "G2 X30 Y30 I5 J5 E22 F900",
        "; --- cool-down sequence ---",
        "M104 S0",
        "M140 S0",
        "G28 X0",
        "M84 ; motors off",
        "; END MANIFEST",
    ]
    est_min = _estimate_print_minutes(mass_kg=ESTIMATED_PE100_KG, layer_mm=LAYER_MM)
    return {
        "part_id": PART_ID,
        "part_label": "Bushing-Joint V1",
        "material": "PE100 (HQRS / recycled HDPE filament)",
        "nozzle_c": NOZZLE_C,
        "bed_c": BED_C,
        "layer_height_mm": LAYER_MM,
        "estimated_pe100_kg": ESTIMATED_PE100_KG,
        "estimated_print_minutes": est_min,
        "gcode_lines": lines,
        "gcode_line_count": len(lines),
        "disclaimer": "Simulated G-code — not machine-ready without CAM + printer profile.",
    }


def material_shortage_alert_payload() -> dict[str, Any]:
    q = load_fab_queue()
    ms = q.get("material_shortage") if isinstance(q.get("material_shortage"), dict) else {}
    if not ms.get("active"):
        return {
            "active": False,
            "headline": "",
            "message": "",
            "detail": "",
        }
    need = float(ms.get("needed_kg") or 0)
    have = float(ms.get("available_kg") or 0)
    pid = str(ms.get("part_id") or PART_ID)
    return {
        "active": True,
        "headline": "Material Shortage",
        "message": "HQRS scrap is insufficient for the R&D fabrication job.",
        "detail": (
            f"Part **{pid}** needs ~{need:.4f} kg PE100 equivalent; vault has **{have:.4f}** kg. "
            "Run the Digital Twin (RUNNING), `python factory/scrap_engine.py --sync-twin`, or `--demo-kg` to build HQRS."
        ),
    }


def enqueue_bushing_joint_v1(*, deduct_scrap: bool = True) -> dict[str, Any]:
    """
    Build manifest, optionally deduct HQRS, update fab_queue.json.
    On insufficient scrap: sets material_shortage.active, does not deduct.
    """
    from factory import scrap_engine

    manifest = build_gcode_manifest_bushing_joint_v1()
    kg = float(manifest["estimated_pe100_kg"])
    q = load_fab_queue()
    now = datetime.now(timezone.utc).isoformat()

    if not deduct_scrap:
        q["last_manifest_summary"] = {
            "part_id": PART_ID,
            "dry_run": True,
            "estimated_pe100_kg": kg,
            "estimated_print_minutes": manifest["estimated_print_minutes"],
            "nozzle_c": NOZZLE_C,
            "saved_utc": now,
        }
        q["last_gcode_manifest"] = {
            "part_id": PART_ID,
            "dry_run": True,
            "nozzle_c": NOZZLE_C,
            "bed_c": BED_C,
            "lines": manifest["gcode_lines"],
            "line_count": manifest["gcode_line_count"],
        }
        save_fab_queue(q)
        return {"ok": True, "dry_run": True, "manifest": manifest, "fab_queue": q}

    ded = scrap_engine.deduct_for_fabrication(
        kg=kg,
        part_id=PART_ID,
        note="fab_engine.enqueue_bushing_joint_v1",
    )
    if not ded.get("ok"):
        inv = scrap_engine.load_inventory()
        have = float(inv.get("total_scrap_kg") or 0)
        q["material_shortage"] = {
            "active": True,
            "needed_kg": round(kg, 6),
            "available_kg": round(have, 6),
            "part_id": PART_ID,
        }
        q["last_manifest_summary"] = {
            "part_id": PART_ID,
            "blocked": True,
            "estimated_pe100_kg": kg,
            "saved_utc": now,
        }
        q["last_gcode_manifest"] = {
            "part_id": PART_ID,
            "blocked": True,
            "lines": manifest["gcode_lines"],
            "line_count": manifest["gcode_line_count"],
        }
        save_fab_queue(q)
        return {
            "ok": False,
            "reason": "material_shortage",
            "manifest": manifest,
            "deduction": ded,
            "fab_queue": q,
        }

    q["material_shortage"] = {
        "active": False,
        "needed_kg": 0.0,
        "available_kg": 0.0,
        "part_id": "",
    }
    prev = q.get("active_job")
    if isinstance(prev, dict) and prev.get("job_id"):
        hist = q.get("history") if isinstance(q.get("history"), list) else []
        hist.append({**prev, "archived_utc": now})
        q["history"] = hist[-40:]

    job_id = f"fab-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    q["active_job"] = {
        "job_id": job_id,
        "part_id": PART_ID,
        "part_label": manifest["part_label"],
        "status": "printing",
        "simulated_progress_pct": SIMULATED_PRINT_PROGRESS_PCT,
        "estimated_print_minutes": manifest["estimated_print_minutes"],
        "nozzle_c": NOZZLE_C,
        "bed_c": BED_C,
        "pe100_consumed_kg": kg,
        "gcode_line_count": manifest["gcode_line_count"],
        "started_utc": now,
    }
    q["last_manifest_summary"] = {
        "job_id": job_id,
        "part_id": PART_ID,
        "estimated_pe100_kg": kg,
        "estimated_print_minutes": manifest["estimated_print_minutes"],
        "nozzle_c": NOZZLE_C,
        "saved_utc": now,
    }
    q["last_gcode_manifest"] = {
        "job_id": job_id,
        "part_id": PART_ID,
        "nozzle_c": NOZZLE_C,
        "bed_c": BED_C,
        "lines": manifest["gcode_lines"],
        "line_count": manifest["gcode_line_count"],
    }
    save_fab_queue(q)
    return {
        "ok": True,
        "manifest": manifest,
        "deduction": ded,
        "fab_queue": q,
    }


def fabrication_dashboard_payload() -> dict[str, Any]:
    """Merged view for /empire/lab-status + UI."""
    q = load_fab_queue()
    job = q.get("active_job") if isinstance(q.get("active_job"), dict) else None
    pct = int(job["simulated_progress_pct"]) if job else 0
    print_success_estimate_pct: float | None = None
    try:
        from factory.robot_training_sim import read_last_training_run

        tr = read_last_training_run()
        if isinstance(tr, dict):
            if tr.get("success_rate_pct") is not None:
                print_success_estimate_pct = float(tr["success_rate_pct"])
            elif tr.get("success_rate") is not None:
                print_success_estimate_pct = round(float(tr["success_rate"]) * 100.0, 1)
    except Exception:
        pass
    gcode_tail: list[str] = []
    lgm = q.get("last_gcode_manifest")
    if isinstance(lgm, dict) and isinstance(lgm.get("lines"), list):
        gcode_tail = [str(x) for x in lgm["lines"][-10:]]

    return {
        "fab_queue_path": str(FAB_QUEUE_PATH).replace("\\", "/"),
        "material_shortage": q.get("material_shortage"),
        "active_job": job,
        "simulated_print_progress_pct": pct,
        "last_manifest_summary": q.get("last_manifest_summary"),
        "print_success_estimate_pct": print_success_estimate_pct,
        "gcode_tail": gcode_tail,
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="THIRAMAI fabrication queue (Bushing-Joint V1)")
    p.add_argument("--dry-run", action="store_true", help="Build manifest only; do not deduct HQRS.")
    args = p.parse_args()
    r = enqueue_bushing_joint_v1(deduct_scrap=not args.dry_run)
    print("FAB_ENGINE_OK", FAB_QUEUE_PATH)
    if r.get("ok"):
        print("Job enqueued." if not r.get("dry_run") else "Dry run — no scrap deducted.")
        m = r.get("manifest") or {}
        print(
            f"  PE100 kg: {m.get('estimated_pe100_kg')}  print ~{m.get('estimated_print_minutes')} min  "
            f"nozzle {m.get('nozzle_c')}C  lines {m.get('gcode_line_count')}"
        )
    else:
        print("BLOCKED:", r.get("reason"), "| See material_shortage in fab_queue.json")


if __name__ == "__main__":
    main()
