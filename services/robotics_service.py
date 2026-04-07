"""
Jarvis Peak — robotics R&D facade: scrap → CAD suggestions, Blender/Onshape integration stubs.

Scrap sources: `factory.scrap_engine` (HQRS JSON) + optional PostgreSQL `inventory` rows
whose sku_name/category hints scrap (caller filters).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CADBackend(str, Enum):
    none = "none"
    blender = "blender"
    onshape = "onshape"


@dataclass
class ScrapMaterial:
    """Normalized feedstock for chassis heuristics."""

    source: str
    material_family: str
    est_mass_kg: float
    notes: str = ""


@dataclass
class ChassisSuggestion:
    """Rule-based suggestion until a full generative CAD loop exists."""

    topology: str
    print_strategy: str
    joint_style: str
    rationale: str
    risk_flags: list[str] = field(default_factory=list)
    blender_script_hint: str = ""
    onshape_feature_hint: str = ""


def load_scrap_from_vault() -> dict[str, Any]:
    """HQRS / twin-backed scrap file (vault/rd_core/scrap_inventory.json)."""
    try:
        from factory.scrap_engine import load_inventory

        return load_inventory()
    except Exception:
        return {}


def scrap_rows_from_inventory_db(
    *,
    organization_id: int | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Optional: inventory lines that look like polymer stock / drip / pipe scrap (tenant-scoped)."""
    try:
        from sqlalchemy import or_, select

        from core.database import get_session_factory
        from core.db.models import Inventory

        factory = get_session_factory()
        if factory is None:
            return []
        hints = ("%pipe%", "%pvc%", "%hdpe%", "%drip%", "%scrap%", "%offcut%")
        with factory() as session:
            stmt = select(Inventory)
            oid = int(organization_id) if organization_id is not None else None
            if oid is not None:
                stmt = stmt.where(
                    or_(Inventory.organization_id == oid, Inventory.organization_id.is_(None))
                )
            else:
                stmt = stmt.where(Inventory.id == -1)
            stmt = stmt.limit(200)
            rows = session.execute(stmt).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            sku = (r.sku_name or "").lower()
            if any(pat.strip("%") in sku for pat in hints):
                out.append(
                    {
                        "sku_name": r.sku_name,
                        "quantity": float(r.quantity),
                        "location": r.location,
                        "total_value": float(r.total_value) if r.total_value else None,
                    }
                )
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _normalize_scrap(inv: dict[str, Any], db_rows: list[dict[str, Any]]) -> list[ScrapMaterial]:
    mats: list[ScrapMaterial] = []
    try:
        kg = float(inv.get("high_quality_scrap_kg") or inv.get("total_scrap_kg") or 0.0)
    except (TypeError, ValueError):
        kg = 0.0
    if kg > 0:
        mats.append(
            ScrapMaterial(
                source="hqrs_json",
                material_family="HDPE_PE_family",
                est_mass_kg=kg,
                notes="HQRS robotics scrap (see scrap_engine)",
            )
        )
    for row in db_rows:
        mats.append(
            ScrapMaterial(
                source=f"inventory:{row.get('sku_name')}",
                material_family="stock_sku",
                est_mass_kg=float(row.get("quantity") or 0.0),
                notes=f"loc={row.get('location')}",
            )
        )
    return mats


def suggest_chassis_from_scrap(
    *,
    target_part: str = "humanoid_torso_segment",
    min_print_mass_kg: float = 0.35,
) -> ChassisSuggestion:
    """
    Scrap-to-CAD heuristic: choose shell thickness & joint pattern from available kg.

    Replace with topology optimization / LLM+CAD agent when Blender bpy or Onshape API is wired.
    """
    inv = load_scrap_from_vault()
    db_rows = scrap_rows_from_inventory_db()
    mats = _normalize_scrap(inv, db_rows)
    total_kg = sum(m.est_mass_kg for m in mats)
    flags: list[str] = []
    if total_kg < min_print_mass_kg:
        flags.append("low_mass_warn")
    if total_kg < min_print_mass_kg * 3:
        topology = "single-shell bracket + clevis stub (minimal mass)"
        joints = "printed revolute pin; metal fastener backup"
        strat = "0.28 mm layers, 3 perimeters, 25% gyroid infill"
    elif total_kg < 2.0:
        topology = "split clam-shell torso with internal rib lattice"
        joints = "bushing-lined clevis (see humanoid_design_v1.md OD 32 mm)"
        strat = "0.2 mm layers, 4 perimeters, 15% infill trunk / 40% joint"
    else:
        topology = "modular torso + shoulder yoke; detachable service panels"
        joints = "PE100 bushing joints + steel shoulder pins for high moment"
        strat = "segmented prints ≤250g per job; anneal protocol per material card"

    rationale = (
        f"HQRS + inventory hint **~{total_kg:.3f} kg** usable feedstock. "
        f"Prefer **recycled HDPE** paths validated by `factory/design_engine.py` before flight hardware."
    )
    return ChassisSuggestion(
        topology=topology,
        print_strategy=strat,
        joint_style=joints,
        rationale=rationale,
        risk_flags=flags,
        blender_script_hint=(
            "bpy.ops.mesh.primitive_cylinder_add for bushing OD 32mm test coupon; "
            "boolean difference for clevis pocket — run headless `blender -b -P export_stl.py`"
        ),
        onshape_feature_hint=(
            "Part Studio: variable `scrap_density`; Extrude rib pattern; export STEP for slicer"
        ),
    )


def blender_api_stub(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Blender 4.x headless: requires `blender` on PATH and a project script.
    This stub documents the contract only.
    """
    _ = payload
    return {
        "ok": False,
        "backend": CADBackend.blender.value,
        "operation": operation,
        "detail": "Set BLENDER_EXECUTABLE and ROBOTICS_BLENDER_SCRIPT to enable; no bpy in this process.",
    }


def onshape_api_stub(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Onshape REST: requires API keys + document/workspace ids in env."""
    _ = payload
    return {
        "ok": False,
        "backend": CADBackend.onshape.value,
        "operation": operation,
        "detail": "Set ONSHAPE_ACCESS_KEY, ONSHAPE_SECRET_KEY, ONSHAPE_DOCUMENT_ID to enable.",
    }


def robotics_lab_payload_for_brain() -> str:
    """Short markdown block for council / CEO context."""
    s = suggest_chassis_from_scrap()
    inv = load_scrap_from_vault()
    return (
        "### Robotics lab (scrap → CAD skeleton)\n"
        f"- **HQRS kg (file):** {inv.get('total_scrap_kg', 0)}\n"
        f"- **Suggested topology:** {s.topology}\n"
        f"- **Joints:** {s.joint_style}\n"
        f"- **Flags:** {', '.join(s.risk_flags) or 'none'}\n"
    )


def export_suggestion_json(suggestion: ChassisSuggestion) -> str:
    return json.dumps(
        {
            "topology": suggestion.topology,
            "print_strategy": suggestion.print_strategy,
            "joint_style": suggestion.joint_style,
            "rationale": suggestion.rationale,
            "risk_flags": suggestion.risk_flags,
        },
        indent=2,
    )
