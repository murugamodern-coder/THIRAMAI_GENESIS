"""
Autonomous action engine: candidate generator only (no direct execution).
"""

from __future__ import annotations

from typing import Any
from services.identity_context_loader import load_master_identity_context


def _to_text(v: Any, n: int = 260) -> str:
    return str(v or "").strip().replace("\n", " ")[:n]


def _score(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    return max(0.0, min(1.0, x))


def _pick_candidates(
    generated_intents: list[dict[str, Any]],
    continuous_thinking: dict[str, Any],
    value_generation: dict[str, Any],
) -> list[dict[str, Any]]:
    intents = [x for x in list(generated_intents or []) if isinstance(x, dict)]
    scored: list[dict[str, Any]] = []
    for i in intents:
        conf = _score(i.get("confidence"), 0.0)
        risk = _score(i.get("risk"), 1.0)
        ma = _score(i.get("mission_alignment"), 0.0)
        safe = bool(i.get("safe_to_execute", risk < 0.65))
        assist = bool(i.get("assist_required", False))
        if not safe or assist:
            continue
        if conf < 0.72 or ma < 0.62 or risk > 0.45:
            continue
        score = (0.40 * conf) + (0.40 * ma) + (0.20 * (1.0 - risk))
        scored.append({**i, "_autonomous_score": round(score, 4)})

    # Add one backup candidate from continuous thinking auto candidates.
    cands = [x for x in list((continuous_thinking or {}).get("self_generated_actions") or []) if isinstance(x, dict)]
    for c in cands[:2]:
        if str(c.get("type") or "") != "auto_action_candidate":
            continue
        txt = _to_text(c.get("title"), 200)
        if not txt:
            continue
        scored.append(
            {
                "intent": txt,
                "why": _to_text(c.get("reason"), 240) or "Candidate from continuous thinking.",
                "expected_outcome": "Low-risk autonomous progression via governed execution.",
                "confidence": 0.74,
                "risk": 0.25,
                "mission_alignment": 0.68,
                "safe_to_execute": True,
                "assist_required": False,
                "_autonomous_score": 0.70,
            }
        )
        break
    scored.sort(key=lambda x: float(x.get("_autonomous_score") or 0.0), reverse=True)
    return scored


def run_autonomous_action_cycle(
    user_id: int,
    organization_id: int,
    *,
    continuous_thinking: dict[str, Any] | None = None,
    generated_intents: list[dict[str, Any]] | None = None,
    value_generation: dict[str, Any] | None = None,
    realtime_research: dict[str, Any] | None = None,
    identity_context: dict[str, Any] | None = None,
    max_autonomous_actions_per_cycle: int = 1,
    cooldown_seconds: int = 180,
    failure_backoff_seconds: int = 600,
) -> dict[str, Any]:
    _ = user_id, organization_id, identity_context, cooldown_seconds, failure_backoff_seconds

    candidates = _pick_candidates(
        generated_intents=[x for x in list(generated_intents or []) if isinstance(x, dict)],
        continuous_thinking=continuous_thinking if isinstance(continuous_thinking, dict) else {},
        value_generation=value_generation if isinstance(value_generation, dict) else {},
    )
    if not candidates:
        return {
            "execution_candidates": [],
            "skipped_actions": [{"reason": "no_safe_high_confidence_candidates"}],
            "reasons": ["no_safe_high_confidence_candidates"],
        }

    max_n = max(1, min(int(max_autonomous_actions_per_cycle), 1))
    execution_candidates: list[dict[str, Any]] = []
    for c in candidates[:max_n]:
        intent_text = _to_text(c.get("intent"), 700)
        if not intent_text:
            continue
        execution_candidates.append(
            {
                "source": "autonomous_action",
                "title": _to_text(c.get("intent"), 200),
                "command": f"Autonomous safe action candidate: {intent_text}. Execute only low-risk internal-safe path.",
                "confidence": _score(c.get("confidence"), 0.0),
                "risk": _score(c.get("risk"), 1.0),
                "mission_alignment": _score(c.get("mission_alignment"), 0.0),
                "priority_score": _score(c.get("_autonomous_score"), 0.0),
                "safe_to_execute": bool(c.get("safe_to_execute", True)),
                "assist_required": bool(c.get("assist_required", False)),
            }
        )
    return {
        "execution_candidates": execution_candidates,
        "skipped_actions": [] if execution_candidates else [{"reason": "no_action_candidate"}],
        "reasons": ["candidate_selected"] if execution_candidates else ["no_action_candidate"],
        "limits": {
            "max_autonomous_actions_per_cycle": max_n,
            "cooldown_seconds": int(cooldown_seconds),
            "failure_backoff_seconds": int(failure_backoff_seconds),
        },
    }

