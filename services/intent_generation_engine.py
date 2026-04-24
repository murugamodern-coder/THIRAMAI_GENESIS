"""
Intent generation engine: synthesize next-action intents from system intelligence outputs.

Safety:
- Produces intents only
- No direct execution
- Action candidates must route via brain_execute/governor
"""

from __future__ import annotations

from typing import Any

from services.identity_context_loader import load_master_identity_context, score_long_term_alignment


def _to_text(v: Any, n: int = 320) -> str:
    return str(v or "").strip().replace("\n", " ")[:n]


def _score(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    return max(0.0, min(1.0, x))


def _risk_to_safe(risk: float) -> bool:
    return float(risk) < 0.65


def generate_intents(
    *,
    realtime_research: dict[str, Any] | None = None,
    value_generation: dict[str, Any] | None = None,
    self_learning: dict[str, Any] | None = None,
    result_execution: dict[str, Any] | None = None,
    identity_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rr = realtime_research if isinstance(realtime_research, dict) else {}
    vg = value_generation if isinstance(value_generation, dict) else {}
    sl = self_learning if isinstance(self_learning, dict) else {}
    rx = result_execution if isinstance(result_execution, dict) else {}
    identity = identity_context if isinstance(identity_context, dict) else load_master_identity_context()

    intents: list[dict[str, Any]] = []

    # Seed 1: top activated/value opportunity.
    activated = [x for x in list(vg.get("activated_opportunities") or []) if isinstance(x, dict)]
    if activated:
        top = sorted(
            activated,
            key=lambda x: (
                _score(x.get("opportunity_score"), 0.0),
                _score(x.get("actionability_score"), 0.0),
                _score(x.get("mission_alignment"), 0.0),
            ),
            reverse=True,
        )[0]
        intent_txt = f"Validate and stage '{_to_text(top.get('title'), 170)}' as the next low-risk opportunity pilot."
        ma = _score(top.get("mission_alignment"), score_long_term_alignment(intent_txt, identity))
        conf = max(0.45, min(0.95, (0.45 * _score(top.get("confidence"), 0.5)) + (0.35 * _score(top.get("actionability_score"), 0.5)) + (0.20 * ma)))
        risk = _score(top.get("risk"), 0.4)
        intents.append(
            {
                "intent": intent_txt,
                "why": "Highest composite opportunity/actionability signal in current cycle.",
                "expected_outcome": "Short-cycle validation plus measurable value hypothesis quality improvement.",
                "confidence": round(conf, 4),
                "risk": round(risk, 4),
                "mission_alignment": round(ma, 4),
            }
        )

    # Seed 2: learning-driven skill gap intent.
    gaps = [x for x in list(sl.get("knowledge_gaps_detected") or []) if isinstance(x, dict)]
    if gaps:
        g = gaps[0]
        intent_txt = f"Close capability gap: {_to_text(g.get('gap'), 140)} through a bounded simulation-first task."
        ma = _score(score_long_term_alignment(intent_txt, identity), 0.5)
        intents.append(
            {
                "intent": intent_txt,
                "why": _to_text(g.get("why"), 220) or "Gap blocks compounding decision quality.",
                "expected_outcome": "Reduced failure recurrence and improved strategy conversion confidence.",
                "confidence": round(max(0.42, min(0.86, 0.48 + (0.30 * ma))), 4),
                "risk": 0.22,
                "mission_alignment": round(ma, 4),
            }
        )

    # Seed 3: result feedback intent.
    failures = [x for x in list(rx.get("failures") or []) if isinstance(x, dict)]
    if failures:
        intent_txt = "Run a stabilization intent targeting recurring failure patterns before scaling new opportunities."
        ma = _score(score_long_term_alignment(intent_txt, identity), 0.5)
        intents.append(
            {
                "intent": intent_txt,
                "why": f"{len(failures)} execution failures observed in recent cycle.",
                "expected_outcome": "Higher success ratio and safer throughput in subsequent cycles.",
                "confidence": round(max(0.5, min(0.9, 0.55 + (0.2 * ma))), 4),
                "risk": 0.20,
                "mission_alignment": round(ma, 4),
            }
        )

    # Seed 4: realtime strategic follow-up intent.
    updates = [x for x in list(rr.get("daily_updates") or []) if isinstance(x, dict)]
    if updates:
        u = updates[0]
        intent_txt = f"Create mission-focused follow-up on realtime signal: {_to_text(u.get('title'), 150)}"
        ma = _score(u.get("mission_alignment"), score_long_term_alignment(intent_txt, identity))
        intents.append(
            {
                "intent": intent_txt,
                "why": "Fresh external signal can create first-mover informational advantage.",
                "expected_outcome": "Improved timing for opportunity capture and risk positioning.",
                "confidence": round(max(0.4, min(0.88, (0.4 * _score(u.get('confidence'), 0.5)) + (0.3 * _score(u.get('importance'), 0.5)) + (0.3 * ma))), 4),
                "risk": round(max(0.12, min(0.55, 0.45 - (0.2 * _score(u.get("actionability_score"), 0.4)))), 4),
                "mission_alignment": round(ma, 4),
            }
        )

    if not intents:
        fallback = "Synthesize one safe, high-alignment optimization intent from current memory and execute only through governed path."
        intents = [
            {
                "intent": fallback,
                "why": "Maintain non-idle strategic progression each cycle.",
                "expected_outcome": "Steady knowledge-to-action conversion quality.",
                "confidence": 0.55,
                "risk": 0.28,
                "mission_alignment": round(score_long_term_alignment(fallback, identity), 4),
            }
        ]
    return intents


def run_intent_generation_cycle(
    *,
    realtime_research: dict[str, Any] | None = None,
    value_generation: dict[str, Any] | None = None,
    self_learning: dict[str, Any] | None = None,
    result_execution: dict[str, Any] | None = None,
    identity_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw = generate_intents(
        realtime_research=realtime_research,
        value_generation=value_generation,
        self_learning=self_learning,
        result_execution=result_execution,
        identity_context=identity_context,
    )
    filtered: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        conf = _score(row.get("confidence"), 0.0)
        risk = _score(row.get("risk"), 1.0)
        ma = _score(row.get("mission_alignment"), 0.0)
        safe = _risk_to_safe(risk)
        if conf < 0.55 or ma < 0.50 or not safe:
            continue
        filtered.append(
            {
                **row,
                "action_candidate": bool(conf >= 0.72 and ma >= 0.62 and safe),
                "safe_to_execute": bool(safe),
                "assist_required": False if safe else True,
                "route": "brain_execute",
                "direct_execution": False,
            }
        )

    if not filtered:
        # Keep one conservative intent so the system always has a next recommendation.
        best = raw[0] if raw and isinstance(raw[0], dict) else {
            "intent": "Run one safe mission-aligned optimization review.",
            "why": "No high-confidence intent passed filter.",
            "expected_outcome": "Prepare stronger intent signals next cycle.",
            "confidence": 0.56,
            "risk": 0.24,
            "mission_alignment": 0.58,
        }
        filtered = [
            {
                **best,
                "action_candidate": False,
                "safe_to_execute": True,
                "assist_required": False,
                "route": "brain_execute",
                "direct_execution": False,
            }
        ]
    return filtered[:8]

