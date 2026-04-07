"""
Sort operator / engine decisions by synthetic urgency + impact, adjusted by ``strategy_memory``.
"""

from __future__ import annotations

from typing import Any

from core.observability import log_structured
from core.strategy_memory import confidence_multiplier_for_decision


# urgency weight component (0..1 scale internally)
_URGENCY: dict[str, float] = {
    "increase_price": 0.95,
    "reduce_cost": 0.92,
    "restock_fast_items": 0.9,
    "marketing_push": 0.88,
    "boost_demand": 0.72,
}

# impact axis contribution
_IMPACT: dict[str, tuple[str, float]] = {
    "increase_price": ("revenue", 0.42),
    "reduce_cost": ("cost", 0.4),
    "restock_fast_items": ("ops", 0.38),
    "marketing_push": ("revenue", 0.4),
    "boost_demand": ("growth", 0.36),
}


def _base_score(decision_key: str) -> float:
    u = _URGENCY.get(decision_key, 0.55)
    _axis, imp = _IMPACT.get(decision_key, ("general", 0.25))
    raw = 0.45 * u + 0.55 * imp
    return max(0.05, min(0.98, raw))


def prioritize_decisions(
    decisions: list[Any],
    *,
    organization_id: int = 0,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return the same decision dicts enriched with ``priority_score`` (higher = sooner), sorted descending.

    Unknown decision keys receive a conservative default score.
    """
    oid = int(organization_id)
    enriched: list[dict[str, Any]] = []

    for raw in decisions:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("decision") or raw.get("decision_type") or "").strip()
        if not key:
            key = "unknown"
        base = _base_score(key)
        mult = confidence_multiplier_for_decision(oid, key) if oid > 0 else 1.0
        score = max(0.01, min(0.99, base * mult))
        row = {**raw, "priority_score": round(score, 4), "_priority_base": round(base, 4), "_confidence_mult": round(mult, 4)}
        enriched.append(row)

    enriched.sort(key=lambda x: float(x.get("priority_score") or 0), reverse=True)

    log_structured(
        "decision_prioritizer.complete",
        request_id=request_id,
        organization_id=oid,
        count=len(enriched),
    )
    return enriched
