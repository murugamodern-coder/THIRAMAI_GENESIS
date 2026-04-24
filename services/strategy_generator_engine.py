"""Strategy generator: create, simulate, research-test, and promote strategies."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.experimentation_engine import complete_experiment, create_experiment_for_strategy, set_experiment_execution
from services.learning_engine import update_strategy_profiles
from services.research_loop_engine import compare_experiment_results, generate_hypotheses, run_experiment
from services.simulation_engine import choose_best_simulated_path
from services.world_model_engine import get_world_model


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_strategies(user_id: int) -> dict[str, Any]:
    world = get_world_model(int(user_id))
    regime = str(((world.get("market_behavior") or {}).get("regime")) or "balanced")
    strategies = [
        {
            "strategy_id": f"strat_{int(datetime.now(timezone.utc).timestamp())}_1",
            "type": "business_idea",
            "title": "Micro-vertical expansion",
            "description": f"Launch niche offering aligned with {regime} regime demand.",
            "expected_profit": 18000.0,
        },
        {
            "strategy_id": f"strat_{int(datetime.now(timezone.utc).timestamp())}_2",
            "type": "revenue_model",
            "title": "Hybrid recurring + performance model",
            "description": "Blend recurring baseline with performance upside.",
            "expected_profit": 24000.0,
        },
        {
            "strategy_id": f"strat_{int(datetime.now(timezone.utc).timestamp())}_3",
            "type": "execution_approach",
            "title": "Automation-first fulfillment lane",
            "description": "Use autonomous lanes to reduce latency and increase throughput.",
            "expected_profit": 15000.0,
        },
    ]
    return {"ok": True, "generated_at": _now_iso(), "items": strategies, "world_regime": regime}


def test_strategies(user_id: int, organization_id: int, strategies: list[dict[str, Any]]) -> dict[str, Any]:
    tested: list[dict[str, Any]] = []
    for s in (strategies or [])[:6]:
        sim = choose_best_simulated_path(int(user_id), {"expected_profit": float(s.get("expected_profit") or 0), "strategy": s})
        hyp = generate_hypotheses(int(user_id), "strategy_generation")
        hyp_id = str(((hyp.get("items") or [{}])[0] or {}).get("title") or s.get("strategy_id") or "strategy_hypothesis")
        hyp_body = str(((hyp.get("items") or [{}])[0] or {}).get("hypothesis") or "Strategy candidate test")
        rec = sim.get("chosen_path") or {}
        se = create_experiment_for_strategy(
            int(user_id),
            int(organization_id),
            s,
            hyp_body,
            experiment_group="strategy_generation",
        )
        exp = run_experiment(
            int(user_id),
            int(organization_id),
            hyp_id,
            {
                "domain": "strategy_generation",
                "baseline_score": 0.5,
                "candidate_score": float(rec.get("success_probability") or 0.5),
            },
        )
        strat_exp: dict[str, Any] | None = None
        if se.get("ok"):
            eid = int(se["experiment_id"])
            set_experiment_execution(
                eid,
                int(user_id),
                {
                    "simulation": sim,
                    "hypothesis_titles": hyp.get("items"),
                    "research_experiment": exp,
                },
            )
            winner_ok = str(exp.get("winner") or "") == "candidate"
            strat_exp = complete_experiment(
                eid,
                int(user_id),
                int(organization_id),
                {
                    "delta": exp.get("delta"),
                    "research_experiment_id": exp.get("experiment_id"),
                    "winner": exp.get("winner"),
                    "simulation_chosen": rec,
                    "ok": exp.get("ok"),
                },
                success=winner_ok,
                sync_strategy_profiles=False,
            )
        tested.append(
            {
                "strategy": s,
                "simulation": sim,
                "experiment": exp,
                "strategy_experiment": strat_exp,
                "strategy_experiment_id": int(se["experiment_id"]) if se.get("ok") else None,
            }
        )
    profile_refresh = update_strategy_profiles(int(user_id)) if tested else None
    return {"ok": True, "items": tested, "strategy_profile_refresh": profile_refresh}


def promote_best_strategy(user_id: int, tested: list[dict[str, Any]]) -> dict[str, Any]:
    if not tested:
        return {"ok": False, "error": "No tested strategies"}
    scored = []
    for item in tested:
        s = item.get("strategy") or {}
        rec = ((item.get("simulation") or {}).get("chosen_path") or {})
        sp = float(rec.get("success_probability") or 0.0)
        ep = float(rec.get("estimated_profit") or float(s.get("expected_profit") or 0))
        rk = float(rec.get("estimated_risk") or 0.5)
        score = (ep * sp) - (rk * ep * 0.4)
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
    validation = compare_experiment_results(int(user_id), "strategy_generation")
    promoted = str(validation.get("recommendation") or "") == "promote"
    return {
        "ok": True,
        "promoted": promoted,
        "best_strategy": best.get("strategy"),
        "simulation_path": ((best.get("simulation") or {}).get("chosen_path") or {}),
        "validation": validation,
    }


def generate_and_promote(user_id: int, organization_id: int) -> dict[str, Any]:
    gen = generate_strategies(int(user_id))
    tested = test_strategies(int(user_id), int(organization_id), gen.get("items") or [])
    promotion = promote_best_strategy(int(user_id), tested.get("items") or [])
    return {"ok": True, "generated": gen, "tested": tested, "promotion": promotion}
