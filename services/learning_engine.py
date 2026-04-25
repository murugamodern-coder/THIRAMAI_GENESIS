"""Self-learning and optimization engine (ML-lite)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select

from core.database import get_session_factory
from core.db.models import LearningLog, StrategyProfile
from services.feedback_engine import calculate_prediction_accuracy


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_outcome(
    *,
    user_id: int,
    organization_id: int,
    source_type: str,
    source_id: int | None,
    input_data: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    outcome_data = outcome or {}
    pnl = float(outcome_data.get("profit_loss") or outcome_data.get("realized_profit") or 0)
    success = bool(outcome_data.get("success")) if "success" in outcome_data else pnl >= 0
    with factory() as session:
        row = LearningLog(
            resolved_by_user_id=int(user_id),
            organization_id=int(organization_id),
            source_type=str(source_type or "")[:32],
            source_id=int(source_id) if source_id else None,
            input_data_json=input_data or {},
            outcome_json=outcome_data,
            success=bool(success),
            outcome="success" if success else "failure",
            action_type=str(source_type or ""),
            lesson_summary=str(outcome_data.get("note") or "Outcome recorded"),
            context=input_data or {},
            result=outcome_data,
        )
        session.add(row)
        session.commit()
        return {"ok": True, "id": int(row.id), "success": bool(success)}


def _fetch_recent_logs(session, user_id: int, limit: int = 120) -> list[LearningLog]:
    q: Select[tuple[LearningLog]] = (
        select(LearningLog)
        .where(LearningLog.resolved_by_user_id == int(user_id))
        .order_by(LearningLog.created_at.desc(), LearningLog.id.desc())
        .limit(max(1, min(int(limit), 1000)))
    )
    return session.execute(q).scalars().all()


def _moving_average(values: list[float], window: int = 5) -> float:
    if not values:
        return 0.0
    win = max(1, min(int(window), len(values)))
    subset = values[:win]
    return float(sum(subset) / len(subset))


def analyze_patterns(user_id: int, limit: int = 120) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        rows = _fetch_recent_logs(session, int(user_id), limit=limit)
        if not rows:
            return {
                "ok": True,
                "win_rate": 0.0,
                "profit_trend": {"ma_short": 0.0, "ma_long": 0.0},
                "best_strategies": [],
                "worst_patterns": [],
                "recommendations": ["Collect more outcomes to generate insights."],
            }

        profits = []
        wins = 0
        by_source: dict[str, dict[str, float]] = {}
        for row in rows:
            out = row.outcome_json or {}
            pnl = float(out.get("profit_loss") or out.get("realized_profit") or 0)
            profits.append(pnl)
            is_win = bool(row.success) if row.success is not None else pnl >= 0
            wins += 1 if is_win else 0
            src = str(row.source_type or "unknown")
            bucket = by_source.setdefault(src, {"count": 0.0, "wins": 0.0, "pnl": 0.0})
            bucket["count"] += 1
            bucket["wins"] += 1 if is_win else 0
            bucket["pnl"] += pnl

        win_rate = wins / max(len(rows), 1)
        ma_short = _moving_average(profits, window=5)
        ma_long = _moving_average(profits, window=20)

        scored = []
        for src, agg in by_source.items():
            cnt = max(agg["count"], 1.0)
            src_win_rate = agg["wins"] / cnt
            avg_pnl = agg["pnl"] / cnt
            score = (src_win_rate * 0.6) + (0.4 * (1.0 if avg_pnl >= 0 else 0.0))
            scored.append({"source_type": src, "win_rate": round(src_win_rate, 3), "avg_pnl": round(avg_pnl, 2), "score": round(score, 3)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[:3]
        worst = list(reversed(scored[-3:])) if scored else []

        recs: list[str] = []
        if win_rate < 0.45:
            recs.append("Avoid high-risk trades until win rate recovers.")
        if ma_short < ma_long:
            recs.append("Reduce position size; short-term profit trend is weakening.")
        if any(x["source_type"] == "opportunity" and x["score"] > 0.6 for x in best):
            recs.append("Focus on supplier arbitrage and high-score opportunities.")
        if not recs:
            recs.append("Current strategy is stable; keep monitoring risk thresholds.")

        return {
            "ok": True,
            "win_rate": round(win_rate, 4),
            "profit_trend": {"ma_short": round(ma_short, 2), "ma_long": round(ma_long, 2)},
            "best_strategies": best,
            "worst_patterns": worst,
            "recommendations": recs,
            "sample_size": len(rows),
        }


def optimize_parameters(user_id: int, domain: str, insights: dict[str, Any]) -> dict[str, Any]:
    domain_norm = str(domain or "business").strip().lower()
    win_rate = float(insights.get("win_rate") or 0)
    trend = insights.get("profit_trend") or {}
    ma_short = float(trend.get("ma_short") or 0)
    ma_long = float(trend.get("ma_long") or 0)
    risk_multiplier = 1.0
    scoring_weights = {"roi": 0.4, "risk": 0.3, "confidence": 0.3}
    if win_rate < 0.5 or ma_short < ma_long:
        risk_multiplier = 0.8
        scoring_weights = {"roi": 0.35, "risk": 0.4, "confidence": 0.25}
    elif win_rate > 0.65 and ma_short >= ma_long:
        risk_multiplier = 1.1
        scoring_weights = {"roi": 0.45, "risk": 0.25, "confidence": 0.3}
    return {
        "domain": domain_norm,
        "risk_threshold_multiplier": risk_multiplier,
        "opportunity_scoring_weights": scoring_weights,
        "last_optimized_at": _now().isoformat(),
    }


def update_strategy_profiles(user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    insights = analyze_patterns(user_id=int(user_id), limit=200)
    feedback = calculate_prediction_accuracy(int(user_id), limit=220)
    if not insights.get("ok"):
        return insights
    profiles = []
    with factory() as session:
        for domain in ("trading", "business"):
            params = optimize_parameters(int(user_id), domain, insights)
            params["feedback_accuracy_pct"] = float(feedback.get("accuracy_pct") or 0)
            params["feedback_trend"] = str(feedback.get("trend") or "stable")
            params["system_trust_score"] = float(feedback.get("system_trust_score") or 50.0)
            perf = float(insights.get("win_rate") or 0) * 100.0
            row = (
                session.execute(
                    select(StrategyProfile).where(
                        StrategyProfile.user_id == int(user_id),
                        StrategyProfile.domain == domain,
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                row = StrategyProfile(user_id=int(user_id), domain=domain)
                session.add(row)
            row.parameters_json = params
            row.performance_score = round(perf, 2)
            row.updated_at = _now()
            session.flush()
            profiles.append(
                {
                    "id": int(row.id),
                    "domain": domain,
                    "performance_score": row.performance_score,
                    "parameters_json": row.parameters_json or {},
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
            )
        session.commit()
    return {"ok": True, "profiles": profiles, "insights": insights, "feedback": feedback}


def get_strategy_profiles(user_id: int) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        rows = (
            session.execute(
                select(StrategyProfile)
                .where(StrategyProfile.user_id == int(user_id))
                .order_by(StrategyProfile.updated_at.desc(), StrategyProfile.id.desc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(r.id),
                "domain": str(r.domain or ""),
                "parameters_json": r.parameters_json or {},
                "performance_score": float(r.performance_score or 0),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
