"""
Intent execution engine: candidate generator only (no direct execution).
"""

from __future__ import annotations

from typing import Any

def _score(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    return max(0.0, min(1.0, x))


def _to_text(v: Any, n: int = 260) -> str:
    return str(v or "").strip().replace("\n", " ")[:n]


def _pick_top_intent(generated_intents: list[dict[str, Any]]) -> dict[str, Any] | None:
    intents = [x for x in list(generated_intents or []) if isinstance(x, dict)]
    candidates: list[dict[str, Any]] = []
    for i in intents:
        if not bool(i.get("action_candidate")):
            continue
        conf = _score(i.get("confidence"), 0.0)
        ma = _score(i.get("mission_alignment"), 0.0)
        risk = _score(i.get("risk"), 1.0)
        safe = bool(i.get("safe_to_execute", risk < 0.65))
        assist = bool(i.get("assist_required", False))
        if not safe or assist:
            continue
        if conf < 0.72 or ma < 0.62 or risk > 0.45:
            continue
        total = (0.45 * conf) + (0.40 * ma) + (0.15 * (1.0 - risk))
        candidates.append({**i, "_intent_score": round(total, 4)})
    if not candidates:
        return None
    candidates.sort(key=lambda x: float(x.get("_intent_score") or 0.0), reverse=True)
    return candidates[0]


def run_intent_execution_cycle(
    user_id: int,
    organization_id: int,
    *,
    generated_intents: list[dict[str, Any]] | None = None,
    identity_context: dict[str, Any] | None = None,
    max_intents_per_cycle: int = 1,
    cooldown_seconds: int = 180,
    failure_backoff_seconds: int = 900,
) -> dict[str, Any]:
    _ = user_id, organization_id, identity_context, cooldown_seconds, failure_backoff_seconds
    max_n = max(1, min(int(max_intents_per_cycle), 1))
    top = _pick_top_intent([x for x in list(generated_intents or []) if isinstance(x, dict)])
    if top is None:
        return {
            "execution_candidates": [],
            "skipped_intents": [{"reason": "no_strong_intent"}],
            "reason": "no_strong_intent",
        }
    candidate = {
        "source": "intent_execution",
        "command": _to_text(top.get("intent"), 1200),
        "confidence": _score(top.get("confidence"), 0.0),
        "risk": _score(top.get("risk"), 1.0),
        "mission_alignment": _score(top.get("mission_alignment"), 0.0),
        "priority_score": _score(top.get("_intent_score"), 0.0),
        "safe_to_execute": bool(top.get("safe_to_execute", True)),
        "assist_required": bool(top.get("assist_required", False)),
        "title": _to_text(top.get("intent"), 200),
    }
    return {
        "execution_candidates": [candidate][:max_n],
        "skipped_intents": [],
        "reason": "candidate_selected",
    }

