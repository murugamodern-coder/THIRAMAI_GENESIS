"""
THIRAMAI Factory — Design / CAD simulation (Phase 8).

Simulates a lightweight material suitability check for **HDPE PE100** used in
3D-printed humanoid chassis parts. Not a substitute for lab tensile tests.

Run from project root:
    python factory/design_engine.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


GRADE = "PE100"
# Typical pipe-grade context (illustrative — validate per batch MFI/density)
MRS_MPA = 10.0
DENSITY_KG_M3 = 960


@dataclass(frozen=True)
class Criterion:
    name: str
    score_0_100: int
    verdict: str
    detail: str


def _clamp_score(n: float) -> int:
    return int(max(0, min(100, round(n))))


def evaluate_pe100_structural_chassis() -> dict[str, Any]:
    """
    Deterministic rule-based suitability model for FDM structural brackets / guards.
    Returns scores and an overall band for reporting.
    """
    criteria: list[Criterion] = []

    # Stiffness vs steel — PE100 is moderate; OK for shells, not primary load paths
    criteria.append(
        Criterion(
            name="Specific stiffness (vs metal primary structure)",
            score_0_100=_clamp_score(52),
            verdict="Conditional",
            detail="Use PE100 for secondary structure, guards, and ducts; pair with metal for moment-carrying links.",
        )
    )

    # Impact / ductility — PE excels
    criteria.append(
        Criterion(
            name="Impact toughness & ductility (workshop drops)",
            score_0_100=_clamp_score(88),
            verdict="Suitable",
            detail="High ductility reduces brittle fracture in guards; watch notch sensitivity on sharp printed corners.",
        )
    )

    # Layer adhesion / anisotropy
    criteria.append(
        Criterion(
            name="FDM layer adhesion & Z-axis weakness",
            score_0_100=_clamp_score(48),
            verdict="Risk-managed",
            detail="Orient layers for hoop stress on bushings; use 4+ perimeters and ≥35% infill for joint blocks.",
        )
    )

    # Chemical / moisture
    criteria.append(
        Criterion(
            name="Moisture & chemical resistance (factory floor)",
            score_0_100=_clamp_score(90),
            verdict="Suitable",
            detail="Low moisture uptake vs nylons; good fit for humid Indian workshop if not UV-stressed long-term.",
        )
    )

    # Creep under load
    criteria.append(
        Criterion(
            name="Creep under constant bolt preload / thermal cycles",
            score_0_100=_clamp_score(45),
            verdict="Conditional",
            detail="Retorque hardware after thermal cycles; avoid PE100 for single-point long cantilevers >45 mm without ribs.",
        )
    )

    avg = sum(c.score_0_100 for c in criteria) / len(criteria)
    if avg >= 72:
        band = "Qualified — proceed with coupon + joint prototypes"
    elif avg >= 55:
        band = "Provisional — structural PE100 allowed for non-critical chassis modules only"
    else:
        band = "Hold — redesign or change material for listed failure modes"

    return {
        "material_grade": GRADE,
        "mrs_nominal_mpa": MRS_MPA,
        "density_kg_m3": DENSITY_KG_M3,
        "criteria": [c.__dict__ for c in criteria],
        "mean_score": round(avg, 2),
        "overall_band": band,
        "disclaimer": "Simulated design gate — confirm with printed tensile coupons and supplier TDS.",
    }


def format_material_suitability_report() -> str:
    data = evaluate_pe100_structural_chassis()
    lines: list[str] = [
        "=" * 56,
        " THIRAMAI MATERIAL SUITABILITY REPORT (simulated CAD/print gate)",
        "=" * 56,
        f"  Grade: {data['material_grade']}  |  MRS (nominal): {data['mrs_nominal_mpa']} MPa",
        f"  Density (ref.): {data['density_kg_m3']} kg/m³",
        f"  Mean criterion score: {data['mean_score']}/100",
        f"  OVERALL: {data['overall_band']}",
        "-" * 56,
    ]
    for c in data["criteria"]:
        lines.append(f"  • {c['name']}")
        lines.append(f"    Score: {c['score_0_100']}/100  |  {c['verdict']}")
        lines.append(f"    {c['detail']}")
        lines.append("")
    lines.append("-" * 56)
    lines.append(f"  {data['disclaimer']}")
    lines.append("=" * 56)
    return "\n".join(lines)


def main() -> None:
    print(format_material_suitability_report())


if __name__ == "__main__":
    main()
