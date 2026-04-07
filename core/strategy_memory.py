"""
Light-weight outcome memory per decision key — adjusts future prioritization (no auto-exec changes).

Uses ``services.experience_buffer.recent_strategy_outcomes``.
"""

from __future__ import annotations

from typing import Any

from core.observability import log_structured


def update_strategy_memory(
    decision: dict[str, Any],
    outcome: dict[str, Any],
    *,
    organization_id: int = 0,
    request_id: str | None = None,
) -> float:
    """
    Persist an outcome row and return the updated **confidence** score for this decision key (0.15–0.95).
    """
    oid = int(organization_id)
    key = str(
        decision.get("decision")
        or decision.get("from_decision")
        or decision.get("decision_type")
        or "unknown"
    ).strip()
    if oid <= 0 or not key:
        return 0.5

    ok = bool(outcome.get("ok")) if "ok" in outcome else bool(outcome.get("success", True))

    try:
        from services.experience_buffer import record_experience

        record_experience(
            source="strategy_memory",
            action=f"outcome.{key}",
            result={
                "decision_key": key,
                "success": ok,
                "detail": str(outcome.get("detail") or outcome.get("message") or "")[:1500],
            },
            success=ok,
            meta={
                "organization_id": oid,
                "decision_key": key,
                "request_id": request_id,
            },
            tags=["strategy_memory", f"org:{oid}", f"decision:{key[:48]}"],
        )
    except Exception:
        pass

    conf = decision_confidence(organization_id=oid, decision_key=key)
    log_structured(
        "strategy_memory.updated",
        request_id=request_id,
        organization_id=oid,
        decision_key=key,
        success=ok,
        confidence=conf,
    )
    return conf


def decision_confidence(*, organization_id: int, decision_key: str) -> float:
    """Rolling confidence from recent recorded outcomes (defaults 0.5 when empty)."""
    oid = int(organization_id)
    key = (decision_key or "").strip()
    if oid <= 0 or not key:
        return 0.5

    try:
        from services.experience_buffer import recent_strategy_outcomes

        rows = recent_strategy_outcomes(organization_id=oid, decision_key=key, limit=12)
    except Exception:
        rows = []

    if not rows:
        return 0.5

    successes = sum(1 for r in rows if r.get("success"))
    n = len(rows)
    # Beta-style smoothing
    conf = (successes + 1.0) / (n + 2.0)
    return max(0.15, min(0.95, round(conf, 4)))


def confidence_multiplier_for_decision(organization_id: int, decision_key: str) -> float:
    """
    Map confidence into a prioritization multiplier (penalize repeated tool failures).

    Range ~0.55–1.0 so marketing / pricing hints are not over-suppressed.
    """
    c = decision_confidence(organization_id=organization_id, decision_key=decision_key)
    try:
        from services.experience_buffer import recent_strategy_outcomes

        rows = recent_strategy_outcomes(organization_id=int(organization_id), decision_key=decision_key, limit=8)
    except Exception:
        rows = []

    if len(rows) >= 3:
        recent_fails = sum(1 for r in rows[:3] if not r.get("success"))
        if recent_fails >= 3:
            return max(0.55, c * 0.62)

    return max(0.62, min(1.0, 0.75 + 0.25 * c))
