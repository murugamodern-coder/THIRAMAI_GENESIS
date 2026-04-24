"""Continuous money loop engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import MoneyLoopConfig, Opportunity, OpportunityProfitLog
from services.execute_mission_store import MissionExecutionContext, create_mission_plan, run_mission_sequentially
from services.feedback_engine import record_prediction_vs_actual
from services.governance_engine import list_execution_logs, log_execution, validate_action
from services.learning_engine import record_outcome, update_strategy_profiles
from services.long_term_memory_engine import store_agent_episode, store_strategy_memory
from services.opportunity_engine import list_opportunities, scan_all_opportunities
from services.profit_optimizer import allocate_capital
from services.predictive_engine import prediction_summary
from services.simulation_engine import choose_best_simulated_path
from services.world_model_engine import get_world_model


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_money_loop_config(user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {
            "user_id": int(user_id),
            "enabled": False,
            "max_daily_capital": 50000.0,
            "max_parallel_missions": 2,
            "risk_level": "medium",
            "auto_execute": False,
            "optimizer_enabled": True,
            "created_at": None,
        }
    with factory() as session:
        row = session.execute(select(MoneyLoopConfig).where(MoneyLoopConfig.user_id == int(user_id))).scalar_one_or_none()
        if row is None:
            return {
                "user_id": int(user_id),
                "enabled": False,
                "max_daily_capital": 50000.0,
                "max_parallel_missions": 2,
                "risk_level": "medium",
                "auto_execute": False,
                "optimizer_enabled": True,
                "created_at": None,
            }
        return {
            "user_id": int(row.user_id),
            "enabled": bool(row.enabled),
            "max_daily_capital": float(row.max_daily_capital or 0),
            "max_parallel_missions": int(row.max_parallel_missions or 1),
            "risk_level": str(row.risk_level or "medium"),
            "auto_execute": bool(row.auto_execute),
            "optimizer_enabled": bool(getattr(row, "optimizer_enabled", True)),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def upsert_money_loop_config(
    *,
    user_id: int,
    enabled: bool | None = None,
    max_daily_capital: float | None = None,
    max_parallel_missions: int | None = None,
    risk_level: str | None = None,
    auto_execute: bool | None = None,
    optimizer_enabled: bool | None = None,
) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        row = session.execute(select(MoneyLoopConfig).where(MoneyLoopConfig.user_id == int(user_id))).scalar_one_or_none()
        if row is None:
            row = MoneyLoopConfig(user_id=int(user_id))
            session.add(row)
        if enabled is not None:
            row.enabled = bool(enabled)
        if max_daily_capital is not None:
            row.max_daily_capital = max(float(max_daily_capital), 0.0)
        if max_parallel_missions is not None:
            row.max_parallel_missions = max(1, int(max_parallel_missions))
        if risk_level is not None:
            row.risk_level = str(risk_level or "medium").strip().lower()
        if auto_execute is not None:
            row.auto_execute = bool(auto_execute)
        if optimizer_enabled is not None:
            row.optimizer_enabled = bool(optimizer_enabled)
        session.commit()
    return get_money_loop_config(int(user_id))


def _is_kill_switch_active(user_id: int) -> bool:
    check = validate_action("money_loop_cycle", {"user_id": int(user_id), "domain": "automation", "payload": {}})
    return not bool(check.get("allowed"))


def _today_profit(user_id: int) -> float:
    factory = _session_factory_or_none()
    if factory is None:
        return 0.0
    since = _now() - timedelta(hours=24)
    with factory() as session:
        rows = (
            session.execute(
                select(OpportunityProfitLog, Opportunity)
                .join(Opportunity, Opportunity.id == OpportunityProfitLog.opportunity_id)
                .where(Opportunity.user_id == int(user_id), OpportunityProfitLog.created_at >= since)
            )
            .all()
        )
        total = 0.0
        for pl, _opp in rows:
            total += float(getattr(pl, "profit_loss_amount", 0) or 0)
        return round(total, 2)


def _failure_streak(user_id: int) -> int:
    logs = list_execution_logs(int(user_id), limit=30).get("items", [])
    streak = 0
    for row in logs:
        status = str(row.get("status") or "").lower()
        if status in {"failed", "error", "blocked"}:
            streak += 1
        else:
            break
    return streak


def _running_missions_estimate(user_id: int) -> int:
    logs = list_execution_logs(int(user_id), limit=100).get("items", [])
    count = 0
    for row in logs:
        if row.get("action_type") == "mission_execute_step" and row.get("status") == "success":
            count += 1
    return count


def run_money_loop_cycle(user_id: int, organization_id: int, role_name: str = "owner") -> dict[str, Any]:
    cfg = get_money_loop_config(int(user_id))
    if not cfg.get("enabled"):
        return {"ok": True, "skipped": True, "reason": "money loop disabled"}
    if _is_kill_switch_active(int(user_id)):
        return {"ok": True, "skipped": True, "reason": "kill switch active or governance blocked"}
    if _failure_streak(int(user_id)) >= 5:
        return {"ok": True, "skipped": True, "reason": "failure streak too high; loop paused"}
    pred = prediction_summary(int(user_id))
    world = get_world_model(int(user_id))
    pred_risk = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    if pred_risk == "high":
        return {
            "ok": True,
            "skipped": True,
            "reason": "predictive engine flagged high risk; skipping this cycle",
            "prediction": pred,
        }

    scan_all_opportunities(user_id=int(user_id), organization_id=int(organization_id))
    opportunities = list_opportunities(int(user_id), limit=120)
    allowed_risk = str(cfg.get("risk_level") or "medium")
    risk_rank = {"low": 1, "medium": 2, "high": 3}
    max_risk = risk_rank.get(allowed_risk, 2)
    filtered = [
        o
        for o in opportunities
        if o.get("status") in {"new", "approved"}
        and risk_rank.get(str(o.get("risk_level") or "medium"), 2) <= max_risk
    ]
    filtered.sort(key=lambda x: (float(x.get("score") or 0), float(x.get("expected_profit") or 0)), reverse=True)

    top_n = max(1, int(cfg.get("max_parallel_missions") or 1))
    total_cap = float(cfg.get("max_daily_capital") or 0)
    if bool(cfg.get("optimizer_enabled", True)):
        allocations = allocate_capital(
            filtered[: max(5, top_n * 3)],
            total_capital=total_cap,
            user_id=int(user_id),
            max_capital_per_opportunity=total_cap / max(top_n, 1),
        )
    else:
        allocations = []
        for opp in filtered[:top_n]:
            req = float((opp.get("metadata_json") or {}).get("required_capital") or 0)
            alloc = min(req if req > 0 else total_cap / max(top_n, 1), total_cap / max(top_n, 1))
            allocations.append(
                {
                    "opportunity_id": int(opp.get("id") or 0),
                    "title": str(opp.get("title") or ""),
                    "risk_level": str(opp.get("risk_level") or "medium"),
                    "score": float(opp.get("score") or 0),
                    "allocated_capital": round(alloc, 2),
                    "expected_return": round(float(opp.get("expected_profit") or 0), 2),
                    "expected_profit": float(opp.get("expected_profit") or 0),
                    "confidence": float((opp.get("metadata_json") or {}).get("confidence") or 0.5),
                }
            )
    if not allocations:
        return {"ok": True, "skipped": True, "reason": "no opportunities within capital/risk guardrails"}

    outcomes = []
    by_id = {int(o.get("id") or 0): o for o in filtered}
    for alloc in allocations[:top_n]:
        opp = by_id.get(int(alloc.get("opportunity_id") or 0))
        if not opp:
            continue
        execution_id = f"money_loop_{int(opp['id'])}_{int(_now().timestamp())}"
        alloc_cap = float(alloc.get("allocated_capital") or 0)
        sim = choose_best_simulated_path(
            int(user_id),
            {
                "expected_profit": float(opp.get("expected_profit") or 0),
                "required_capital": alloc_cap,
                "opportunity_id": int(opp["id"]),
            },
        )
        path = sim.get("chosen_path") or {}
        if float(path.get("success_probability") or 0) < 0.35:
            outcomes.append(
                {
                    "opportunity_id": int(opp["id"]),
                    "allocation": alloc,
                    "result": {"ok": True, "skipped": True, "reason": "simulation low success probability", "simulation": path},
                }
            )
            continue
        check = validate_action(
            "money_loop_execute",
            {
                "user_id": int(user_id),
                "domain": "automation",
                "payload": {"opportunity_id": int(opp["id"]), "trade_amount": alloc_cap},
            },
        )
        if not check.get("allowed"):
            result = {"ok": False, "blocked": True, "reason": check.get("reason") or "governance blocked"}
            log_execution(
                user_id=int(user_id),
                action_type="money_loop_execute",
                source="automation",
                payload_json={"opportunity_id": int(opp["id"]), "title": opp.get("title")},
                result_json=result,
                status="blocked",
                execution_id=execution_id,
                reasoning_summary="Money loop action blocked by governance.",
                why_action_taken="Opportunity selected by score/risk but denied by guardrails.",
                data_influenced_json={
                    "opportunity_score": opp.get("score"),
                    "risk_level": opp.get("risk_level"),
                    "allocated_capital": alloc_cap,
                },
            )
            outcomes.append({"opportunity_id": int(opp["id"]), "allocation": alloc, "result": result})
            continue

        mission = create_mission_plan(user_id=int(user_id), command=f"money loop execute: {opp.get('title')}")
        executed = None
        if mission and bool(cfg.get("auto_execute")):
            executed = run_mission_sequentially(
                mission_id=int(mission["mission_id"]),
                ctx=MissionExecutionContext(
                    user_id=int(user_id),
                    organization_id=int(organization_id),
                    role_name=str(role_name or "owner"),
                ),
            )
        result = {"ok": True, "mission_id": mission.get("mission_id") if mission else None, "auto_executed": bool(cfg.get("auto_execute")), "execution": executed}
        log_execution(
            user_id=int(user_id),
            action_type="money_loop_execute",
            source="automation",
            payload_json={"opportunity_id": int(opp["id"]), "title": opp.get("title")},
            result_json=result,
            status="success",
            execution_id=execution_id,
            reasoning_summary="Money loop selected top-ranked opportunity for execution.",
            why_action_taken="Opportunity passed capital/risk filters and governance validation.",
            data_influenced_json={
                "opportunity_score": opp.get("score"),
                "risk_level": opp.get("risk_level"),
                "required_capital": (opp.get("metadata_json") or {}).get("required_capital"),
                "allocated_capital": alloc_cap,
            },
        )
        record_outcome(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="opportunity",
            source_id=int(opp["id"]),
            input_data={
                "title": opp.get("title"),
                "score": opp.get("score"),
                "allocated_capital": alloc_cap,
                "expected_profit": float(opp.get("expected_profit") or 0),
            },
            outcome={
                "success": True,
                "profit_loss": float(opp.get("expected_profit") or 0) * 0.5,
                "allocation_vs_actual": {
                    "allocated_capital": alloc_cap,
                    "expected_profit": float(opp.get("expected_profit") or 0),
                    "actual_profit": float(opp.get("expected_profit") or 0) * 0.5,
                },
                "note": "Money loop cycle outcome",
            },
        )
        actual_profit = float(opp.get("expected_profit") or 0) * 0.5
        record_prediction_vs_actual(
            execution_id=execution_id,
            predicted={
                "profit": float(opp.get("expected_profit") or 0),
                "confidence": float((opp.get("metadata_json") or {}).get("confidence") or alloc.get("confidence") or 0.5),
                "strategy": str(opp.get("type") or "opportunity"),
                "source_type": "money_loop",
                "success": True,
            },
            actual={
                "profit": actual_profit,
                "success": bool(actual_profit >= 0),
            },
            user_id=int(user_id),
            organization_id=int(organization_id),
        )
        store_agent_episode(
            user_id=int(user_id),
            execution_id=execution_id,
            goal_id=None,
            outcome={
                "opportunity_id": int(opp["id"]),
                "allocated_capital": alloc_cap,
                "expected_profit": float(opp.get("expected_profit") or 0),
                "actual_profit": actual_profit,
            },
        )
        store_strategy_memory(
            user_id=int(user_id),
            strategy_event={
                "strategy": "money_loop",
                "execution_id": execution_id,
                "risk_level": opp.get("risk_level"),
                "score": opp.get("score"),
            },
        )
        outcomes.append({"opportunity_id": int(opp["id"]), "allocation": alloc, "result": result})

    update_strategy_profiles(int(user_id))
    return {
        "ok": True,
        "processed": len(allocations[:top_n]),
        "capital_allocation": allocations[:top_n],
        "outcomes": outcomes,
        "prediction": pred,
        "world_model": world,
        "today_profit": _today_profit(int(user_id)),
        "running_missions": _running_missions_estimate(int(user_id)),
    }


def money_loop_status(user_id: int) -> dict[str, Any]:
    cfg = get_money_loop_config(int(user_id))
    logs_out = list_execution_logs(int(user_id), limit=30)
    logs = logs_out.get("items", [])
    loop_actions = [x for x in logs if x.get("action_type") == "money_loop_execute"][:10]
    return {
        "ok": True,
        "config": cfg,
        "today_profit": _today_profit(int(user_id)),
        "running_missions": _running_missions_estimate(int(user_id)),
        "failure_streak": _failure_streak(int(user_id)),
        "last_actions": loop_actions,
        "capital_allocation": [
            {
                "opportunity_id": int(((x.get("payload_json") or {}).get("opportunity_id") or 0)),
                "title": (x.get("payload_json") or {}).get("title"),
                "allocated_capital": float(((x.get("data_influenced_json") or {}).get("allocated_capital") or 0)),
                "expected_return": float(((x.get("result_json") or {}).get("execution") or {}).get("expected_return") or 0),
            }
            for x in loop_actions
        ],
        "prediction": prediction_summary(int(user_id)),
        "daily_usage": (logs_out.get("summary") or {}).get("daily_usage", 0),
        "risk_exposure": (logs_out.get("summary") or {}).get("risk_exposure", 0),
    }
