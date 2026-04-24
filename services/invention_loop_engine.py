"""
Invention loop: gaps → ideas → hypotheses → (simulation | research) → compare → promote.
Builds on opportunities, world model, simulation, and research_experiment trail.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import Opportunity
from services.learning_engine import record_outcome, update_strategy_profiles
from services.predictive_engine import prediction_summary
from services.research_engine_service import run_supplier_research_sync
from services.research_loop_engine import generate_hypotheses, run_experiment
from services.simulation_engine import choose_best_simulated_path
from services.world_model_engine import get_world_model


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _list_recent_opportunities(user_id: int, limit: int = 15) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        rows = (
            session.execute(
                select(Opportunity)
                .where(Opportunity.user_id == int(user_id))
                .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
                .limit(max(1, min(50, int(limit))))
            )
            .scalars()
            .all()
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r.id),
                "type": str(r.type or ""),
                "title": str(r.title or ""),
                "status": str(r.status or ""),
                "expected_profit": float(r.expected_profit or 0),
                "risk_level": str(r.risk_level or ""),
            }
        )
    return out


def collect_innovation_gaps(user_id: int, organization_id: int) -> dict[str, Any]:
    world = get_world_model(int(user_id))
    pred = prediction_summary(int(user_id))
    opps = _list_recent_opportunities(int(user_id), limit=15)
    gaps: list[dict[str, Any]] = []
    bdyn = (world or {}).get("business_dynamics") or {}
    execq = str(bdyn.get("execution_quality") or "")
    mreg = str(((world or {}).get("market_behavior") or {}).get("regime") or "balanced")
    trend = str(((pred.get("profit_trend") or {}).get("trend")) or "unknown")
    risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    if risk == "high" or mreg == "defensive" or "fragile" in execq:
        gaps.append(
            {
                "id": "risk_execution",
                "label": "Risk / execution fragility",
                "description": "Market or internal execution signals favor caution; innovation should reduce variance.",
                "severity": "high" if risk == "high" else "medium",
            }
        )
    if trend == "down":
        gaps.append(
            {
                "id": "profit_trend",
                "label": "Weakening short-term profit signal",
                "description": "Outcome momentum is soft; structural or product-side experiments are prioritized.",
                "severity": "medium",
            }
        )
    if len(opps) < 2:
        gaps.append(
            {
                "id": "pipeline",
                "label": "Opportunity pipeline thin",
                "description": "Few new opportunities in queue; ideation and discovery sprints are indicated.",
                "severity": "medium" if len(opps) == 0 else "low",
            }
        )
    if not gaps:
        gaps.append(
            {
                "id": "explore",
                "label": "Exploratory innovation",
                "description": "No acute gap flagged; run lightweight experiments to find upside.",
                "severity": "low",
            }
        )
    return {
        "ok": True,
        "gaps": gaps,
        "context": {
            "world_regime": mreg,
            "profit_trend": trend,
            "risk_level": risk,
            "opportunity_count": len(opps),
            "recent_opportunities": opps[:5],
        },
    }


def _new_idea_id(prefix: str) -> str:
    h = hashlib.md5(f"{prefix}:{time.time()}".encode(), usedforsecurity=False).hexdigest()[:10]
    return f"inv_{h}"


def ideas_from_gaps(
    user_id: int,
    organization_id: int,
    max_ideas: int = 4,
) -> dict[str, Any]:
    g = collect_innovation_gaps(int(user_id), int(organization_id))
    if not g.get("ok"):
        return g
    ctx = g.get("context") or {}
    opps = ctx.get("recent_opportunities") or []
    first_opp = (opps[0] or {}) if opps else {}
    ideas: list[dict[str, Any]] = []
    for gap in (g.get("gaps") or [])[:3]:
        gid = str((gap or {}).get("id") or "gap")
        if gid in ("risk_execution",):
            ideas.append(
                {
                    "idea_id": _new_idea_id("edge"),
                    "title": "Variance-aware operating bundle",
                    "one_liner": "Bundle small vendor contracts and standardize handoffs to cut execution slippage.",
                    "source_gap": gid,
                    "expected_profit": 22000.0,
                    "novelty": "defensive",
                }
            )
        if gid in ("profit_trend",):
            ideas.append(
                {
                    "idea_id": _new_idea_id("rev"),
                    "title": "Margin micro-pilot on top SKU or service",
                    "one_liner": "A/B test pricing, packaging, or service tier on a single high-visibility line.",
                    "source_gap": gid,
                    "expected_profit": 18500.0,
                    "novelty": "incremental",
                }
            )
        if gid in ("pipeline", "explore"):
            ideas.append(
                {
                    "idea_id": _new_idea_id("pipe"),
                    "title": "Signal-led demand discovery",
                    "one_liner": "Synthesize 2–3 adjacent use cases from weak signals in operations or sales.",
                    "source_gap": gid,
                    "expected_profit": 15000.0,
                    "novelty": "exploratory",
                }
            )
    if first_opp.get("title") and first_opp.get("expected_profit", 0) is not None:
        ideas.append(
            {
                "idea_id": _new_idea_id("opp"),
                "title": f"Extend: {str(first_opp.get('title'))[:80]}",
                "one_liner": "Compound an existing live opportunity with a time-boxed follow-through experiment.",
                "source_gap": "opportunity",
                "expected_profit": float(max(first_opp.get("expected_profit") or 8000, 8000)),
                "novelty": "compound",
            }
        )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in ideas:
        t = it.get("title")
        if t in seen or not t:
            continue
        seen.add(str(t))
        out.append(it)
    if not out:
        out.append(
            {
                "idea_id": _new_idea_id("def"),
                "title": "Default micro-experiment: customer touchpoint",
                "one_liner": "Map one new touchpoint in the value chain and time-box a single measurable lift.",
                "source_gap": "default",
                "expected_profit": 12000.0,
                "novelty": "foundational",
            }
        )
    return {"ok": True, "ideas": out[: max(1, min(8, int(max_ideas)))], "gaps": g.get("gaps")}


def create_hypotheses_for_idea(user_id: int, idea: dict[str, Any]) -> dict[str, Any]:
    base = generate_hypotheses(int(user_id), "invention")
    h_text = f"If we pilot «{str(idea.get('title') or 'idea')}», we will observe positive risk-adjusted outcome because it targets the gap {str(idea.get('source_gap') or 'unknown')}"
    return {
        "ok": True,
        "base_hypotheses": (base or {}).get("items") or [],
        "invention_hypothesis": {
            "title": f"Invention: {str(idea.get('idea_id') or 'idea')[:24]}",
            "hypothesis": h_text,
        },
    }


def _score_from_research(idea: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    q = f"Market feasibility and supply landscape for: {str(idea.get('title') or idea.get('one_liner') or 'business idea')[:200]}"
    try:
        r = run_supplier_research_sync(q, max_results=10)
    except Exception as e:  # noqa: BLE001
        return 0.52, {"ok": False, "error": str(e), "fallback": True}
    if not (r and r.get("ok") is not False):
        n = 0
    else:
        n = len(r.get("suppliers") or r.get("links") or [])
    # Map evidence density into [0.45, 0.92] candidate space for experiment vs baseline 0.5
    c = 0.48 + min(0.44, 0.04 * min(n, 8))
    return c, (r or {"ok": True, "n_hints": n})


def _score_from_simulation(user_id: int, idea: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    ctx = {"expected_profit": float(idea.get("expected_profit") or 12000.0), "strategy": idea, "invention_idea": idea}
    sim = choose_best_simulated_path(int(user_id), ctx)
    path = (sim or {}).get("chosen_path") or {}
    p = float(path.get("success_probability") or 0.55)
    p = max(0.1, min(0.95, p))
    return p, sim or {}


def validate_idea(
    user_id: int,
    organization_id: int,
    idea: dict[str, Any],
    method: str = "simulation",
) -> dict[str, Any]:
    m = str(method or "simulation").lower()
    if m not in ("simulation", "research", "both"):
        m = "simulation"
    rmeta: dict[str, Any] = {}
    sim_result: dict[str, Any] = {}
    cand: float
    if m in ("simulation", "both"):
        cand, sim_result = _score_from_simulation(int(user_id), idea)
    else:
        cand = 0.5
    if m in ("research", "both"):
        rcand, rmeta = _score_from_research(idea)
        if m == "both":
            cand = 0.55 * float(cand) + 0.45 * float(rcand)
        else:
            cand = float(rcand)
    hyp = f"invention_{str(idea.get('idea_id') or 'x')[:40]}"
    variant: dict[str, Any] = {
        "domain": "invention_loop",
        "baseline_score": 0.5,
        "candidate_score": float(cand),
        "invention_idea": {k: idea.get(k) for k in ("idea_id", "title", "one_liner", "source_gap", "novelty") if k in idea},
        "validation_method": m,
    }
    if m != "simulation":
        variant["research_ok"] = bool((rmeta or {}).get("ok", True) is not False)
    re = run_experiment(
        int(user_id),
        int(organization_id),
        hyp,
        variant,
    )
    return {
        "ok": True,
        "idea": idea,
        "method": m,
        "candidate_score": round(float(cand), 4),
        "simulation": sim_result if m != "research" else None,
        "research": rmeta if m != "simulation" else None,
        "experiment": re,
    }


def compare_invention_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for r in runs or []:
        ex = (r or {}).get("experiment") or {}
        delta = float((ex or {}).get("delta") or 0)
        c = float((r or {}).get("candidate_score") or 0)
        idea = (r or {}).get("idea") or {}
        composite = delta * 0.65 + (c - 0.5) * 0.5
        scored.append((float(composite), {**r, "composite": round(composite, 4)}))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return {
            "ok": True,
            "ranked": [],
            "recommendation": "hold",
            "best": None,
        }
    best = scored[0][1]
    rec = "promote" if (best.get("experiment") or {}).get("delta", 0) >= 0 else "hold"
    return {
        "ok": True,
        "ranked": [s[1] for s in scored],
        "recommendation": rec,
        "best": best,
    }


def promote_best_idea(
    user_id: int,
    organization_id: int,
    best: dict[str, Any] | None,
) -> dict[str, Any]:
    if not (best and isinstance(best, dict)) or not (best.get("idea")):
        return {"ok": False, "error": "No best idea to promote", "promoted": False}
    dlt = float((best.get("experiment") or {}).get("delta") or 0.0)
    up = update_strategy_profiles(int(user_id))
    rec = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="invention_loop",
        source_id=None,
        input_data={"best_idea": best.get("idea"), "experiment": best.get("experiment")},
        outcome={
            "success": dlt >= 0,
            "profit_loss": 1.0 if dlt >= 0 else -1.0,
            "note": "Invention loop promoted a candidate idea for execution.",
        },
    )
    return {
        "ok": True,
        "promoted": bool((best.get("experiment") or {}).get("delta", 0) >= 0),
        "innovation_pick": best.get("idea"),
        "strategy_update": up,
        "learning_log": rec,
    }


def run_invention_loop(
    user_id: int,
    organization_id: int,
    *,
    validation: str = "simulation",
    max_ideas: int = 4,
) -> dict[str, Any]:
    """Full path: gaps → ideas → per-idea hypotheses → validate + experiment → compare → (conditional) promote."""
    g = ideas_from_gaps(int(user_id), int(organization_id), max_ideas=int(max_ideas))
    if not g.get("ok"):
        return g
    ideas = g.get("ideas") or []
    hy_block: list[dict[str, Any]] = []
    for idea in ideas:
        hy_block.append(create_hypotheses_for_idea(int(user_id), idea))
    runs: list[dict[str, Any]] = []
    for idea in ideas:
        vp = validate_idea(int(user_id), int(organization_id), idea, method=str(validation or "simulation"))
        if vp.get("ok"):
            runs.append(
                {
                    "idea": idea,
                    "experiment": (vp or {}).get("experiment"),
                    "candidate_score": (vp or {}).get("candidate_score"),
                    "method": (vp or {}).get("method"),
                }
            )
    cmp = compare_invention_runs(runs)
    best = (cmp or {}).get("best")
    prom: dict[str, Any] = {"ok": True, "skipped": True}
    if (cmp or {}).get("recommendation") == "promote" and best and (best.get("experiment") or {}).get("delta", 0) > -1e-9:
        prom = promote_best_idea(int(user_id), int(organization_id), best)
    return {
        "ok": True,
        "gaps": collect_innovation_gaps(int(user_id), int(organization_id)),
        "ideas": ideas,
        "hypotheses": hy_block,
        "validations": runs,
        "comparison": cmp,
        "promotion": prom,
    }
