"""Cross-cutting experimentation: every strategy run gets a row; outcomes feed learning + strategy profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from core.database import get_session_factory
from core.db.models import StrategyExperiment
from services.learning_engine import record_outcome, update_strategy_profiles


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def create_experiment_for_strategy(
    user_id: int,
    organization_id: int,
    strategy: dict[str, Any],
    hypothesis: str,
    *,
    experiment_group: str = "default",
) -> dict[str, Any]:
    """Create a DB experiment for a strategy (hypothesis + snapshot; status=running)."""
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    sid = str((strategy or {}).get("strategy_id") or (strategy or {}).get("id") or "unnamed")[:160]
    with factory() as session:
        row = StrategyExperiment(
            user_id=int(user_id),
            organization_id=int(organization_id),
            strategy_id=sid,
            experiment_group=str(experiment_group or "default")[:64],
            strategy_snapshot_json=dict(strategy or {}),
            hypothesis=str(hypothesis or "")[:20000],
            status="running",
        )
        session.add(row)
        session.commit()
        eid = int(row.id)
    return {"ok": True, "experiment_id": eid, "strategy_id": sid, "status": "running"}


def set_experiment_execution(
    experiment_id: int,
    user_id: int,
    execution: dict[str, Any],
) -> dict[str, Any]:
    """Attach execution context (simulation, research run, tool calls)."""
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.get(StrategyExperiment, int(experiment_id))
        if row is None or int(row.user_id) != int(user_id):
            return {"ok": False, "error": "Experiment not found"}
        row.execution_json = {**(row.execution_json or {}), **(execution or {})}
        row.updated_at = _now()
        session.commit()
    return {"ok": True, "experiment_id": int(experiment_id)}


def complete_experiment(
    experiment_id: int,
    user_id: int,
    organization_id: int,
    result: dict[str, Any],
    *,
    success: bool | None = None,
    sync_strategy_profiles: bool = True,
) -> dict[str, Any]:
    """
    Mark completed, store result, write LearningLog via learning engine, optionally refresh StrategyProfile.
    """
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    res = result or {}
    pnl = float(res.get("profit_loss") or res.get("realized_profit") or res.get("delta") or 0.0)
    if success is None:
        if "success" in res:
            success = bool(res.get("success"))
        else:
            success = pnl >= 0 and bool(res.get("ok", True))
    with factory() as session:
        row = session.get(StrategyExperiment, int(experiment_id))
        if row is None or int(row.user_id) != int(user_id):
            return {"ok": False, "error": "Experiment not found"}
        row.result_json = res
        row.success = bool(success) if success is not None else None
        row.status = "completed"
        row.completed_at = _now()
        row.updated_at = _now()
        session.commit()
        snap = row.strategy_snapshot_json or {}
        hyp = str(row.hypothesis or "")
        strat_key = str(snap.get("strategy_id") or row.strategy_id or "")

    ll = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="strategy_experiment",
        source_id=int(experiment_id),
        input_data={
            "hypothesis": hyp,
            "strategy_id": strat_key,
            "strategy": snap,
        },
        outcome={
            **res,
            "success": bool(success) if success is not None else None,
            "profit_loss": pnl,
            "note": f"Experiment {experiment_id} closed; outcome stored.",
        },
    )
    if not ll.get("ok"):
        return {**ll, "experiment_id": int(experiment_id)}

    ll_id = int(ll.get("id") or 0)
    with factory() as session:
        row = session.get(StrategyExperiment, int(experiment_id))
        if row is not None and ll_id:
            row.learning_log_id = ll_id
            row.updated_at = _now()
            session.commit()

    profile_update: dict[str, Any] | None = None
    if sync_strategy_profiles:
        profile_update = update_strategy_profiles(int(user_id))
    return {
        "ok": True,
        "experiment_id": int(experiment_id),
        "learning_log_id": ll_id,
        "success": bool(success) if success is not None else None,
        "strategy_profiles": profile_update,
    }


def run_strategy_trial(
    user_id: int,
    organization_id: int,
    strategy: dict[str, Any],
    hypothesis: str,
    execution_payload: dict[str, Any],
    result_payload: dict[str, Any],
    *,
    experiment_group: str = "strategy_workspace",
    success: bool | None = None,
    sync_strategy_profiles: bool = False,
) -> dict[str, Any]:
    """
    One-shot: create → execution → complete (for strategy tests / simulators without separate calls).
    """
    c = create_experiment_for_strategy(
        int(user_id), int(organization_id), strategy, str(hypothesis or ""), experiment_group=str(experiment_group)
    )
    if not c.get("ok"):
        return c
    eid = int(c["experiment_id"])
    e = set_experiment_execution(int(eid), int(user_id), dict(execution_payload or {}))
    if not e.get("ok"):
        return e
    return complete_experiment(
        eid, int(user_id), int(organization_id), result_payload, success=success, sync_strategy_profiles=sync_strategy_profiles
    )


def compare_success_failure_patterns(
    user_id: int,
    *,
    experiment_group: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Aggregate success vs failure and patterns by strategy type in snapshot."""
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    lim = max(1, min(500, int(limit)))
    with factory() as session:
        q = select(StrategyExperiment).where(StrategyExperiment.user_id == int(user_id), StrategyExperiment.status == "completed")
        if experiment_group:
            q = q.where(StrategyExperiment.experiment_group == str(experiment_group)[:64])
        rows = (session.execute(q.order_by(StrategyExperiment.created_at.desc(), StrategyExperiment.id.desc()).limit(lim)).scalars().all())
    n_ok = sum(1 for r in rows if r.success is True)
    n_fail = sum(1 for r in rows if r.success is False)
    n_unk = sum(1 for r in rows if r.success is None)
    by_type: dict[str, dict[str, int]] = {}
    for r in rows:
        snap = r.strategy_snapshot_json or {}
        t = str(snap.get("type") or "unknown")[:32]
        b = by_type.setdefault(t, {"n": 0, "wins": 0, "losses": 0})
        b["n"] += 1
        if r.success is True:
            b["wins"] += 1
        elif r.success is False:
            b["losses"] += 1
    patterns = [
        {
            "strategy_type": t,
            "n": v["n"],
            "wins": v["wins"],
            "losses": v["losses"],
            "win_rate": round((v["wins"] / max(v["n"], 1)) * 100.0, 1),
        }
        for t, v in by_type.items()
    ]
    patterns.sort(key=lambda x: x["n"], reverse=True)
    return {
        "ok": True,
        "sample_size": len(rows),
        "successes": n_ok,
        "failures": n_fail,
        "unknown": n_unk,
        "success_rate_pct": round((n_ok / max(n_ok + n_fail + n_unk, 1)) * 100.0, 1),
        "by_strategy_type": patterns[:16],
    }


def list_experiment_history(
    user_id: int,
    *,
    experiment_group: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable", "items": []}
    lim = max(1, min(200, int(limit)))
    off = max(0, int(offset))
    with factory() as session:
        q = select(func.count()).select_from(StrategyExperiment).where(StrategyExperiment.user_id == int(user_id))
        if experiment_group:
            q = q.where(StrategyExperiment.experiment_group == str(experiment_group)[:64])
        total = int(session.execute(q).scalar() or 0)
        r2 = select(StrategyExperiment).where(StrategyExperiment.user_id == int(user_id))
        if experiment_group:
            r2 = r2.where(StrategyExperiment.experiment_group == str(experiment_group)[:64])
        rows = (
            session.execute(r2.order_by(StrategyExperiment.created_at.desc(), StrategyExperiment.id.desc()).offset(off).limit(lim))
            .scalars()
            .all()
        )
    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "id": int(r.id),
                "strategy_id": str(r.strategy_id or ""),
                "experiment_group": str(r.experiment_group or ""),
                "status": str(r.status or ""),
                "success": r.success,
                "hypothesis": (r.hypothesis or "")[:500],
                "summary": {
                    "execution_keys": list((r.execution_json or {}).keys())[:20],
                    "result_keys": list((r.result_json or {}).keys())[:20],
                },
                "learning_log_id": r.learning_log_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
        )
    return {"ok": True, "items": items, "total": total, "offset": off, "limit": lim}
