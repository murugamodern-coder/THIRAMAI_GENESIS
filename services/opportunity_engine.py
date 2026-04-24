"""Intelligent money-making opportunity engine."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select

from core.database import get_session_factory
from core.db.models import Opportunity, OpportunityProfitLog
from services.automation_rule_engine import evaluate_rules
from services.business_snapshot_service import build_business_snapshot
from services.execute_mission_store import MissionExecutionContext, create_mission_plan, run_mission_sequentially
from services.learning_engine import record_outcome, update_strategy_profiles
from services.research_engine_service import run_supplier_research_sync
from services.stock_signal_service import generate_intraday_signal


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _risk_score(risk_level: str) -> float:
    r = str(risk_level or "").lower()
    if r == "low":
        return 0.8
    if r == "high":
        return 0.3
    return 0.55


def _compute_score(expected_profit: float, risk_level: str, confidence: float, required_capital: float) -> float:
    cap = max(required_capital, 1.0)
    roi = max(float(expected_profit), 0.0) / cap
    score = (roi * 40.0) + (_risk_score(risk_level) * 30.0) + (max(min(float(confidence), 1.0), 0.0) * 30.0)
    return round(score, 2)


def _insert_opportunity(
    *,
    user_id: int,
    opp_type: str,
    title: str,
    description: str,
    expected_profit: float,
    risk_level: str,
    metadata_json: dict[str, Any],
) -> int | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        row = Opportunity(
            user_id=int(user_id),
            type=str(opp_type or "business"),
            title=str(title or "")[:300],
            description=str(description or ""),
            expected_profit=float(expected_profit or 0),
            risk_level=str(risk_level or "medium"),
            status="new",
            metadata_json=metadata_json or {},
        )
        session.add(row)
        session.commit()
        return int(row.id)


def scan_trading_opportunities(user_id: int, symbol: str = "TCS") -> dict[str, Any]:
    out = generate_intraday_signal(symbol, user_id=int(user_id))
    if not out.get("ok"):
        return {"ok": False, "error": out.get("error") or "Trading scan failed"}
    action = str(out.get("action") or "HOLD")
    if action == "HOLD":
        return {"ok": True, "created": False, "reason": "No strong trading opportunity"}
    expected_profit = abs(float(out.get("target_price") or 0) - float(out.get("entry_price") or 0)) * 10
    required_capital = float(out.get("entry_price") or 0) * 10
    confidence = 0.7 if action == "BUY" else 0.62
    metadata = {
        "symbol": symbol,
        "signal": out,
        "required_capital": required_capital,
        "confidence": confidence,
        "score": _compute_score(expected_profit, "medium", confidence, required_capital),
        "approval_required": True,
    }
    oid = _insert_opportunity(
        user_id=int(user_id),
        opp_type="trading",
        title=f"{symbol} {action} setup",
        description=str(out.get("reasoning") or "Trading setup detected"),
        expected_profit=expected_profit,
        risk_level="medium",
        metadata_json=metadata,
    )
    if oid is None:
        return {"ok": False, "error": "Unable to persist opportunity"}
    return {"ok": True, "created": True, "opportunity_id": oid}


def scan_business_opportunities(user_id: int, organization_id: int) -> dict[str, Any]:
    snapshot = build_business_snapshot(int(organization_id))
    if not snapshot.get("ok"):
        return {"ok": False, "error": snapshot.get("error") or "Business scan failed"}
    net = float(snapshot.get("net_profit") or 0)
    revenue = float(snapshot.get("revenue") or 0)
    margin = (net / revenue) if revenue > 0 else 0
    if margin > 0.14:
        return {"ok": True, "created": False, "reason": "Margins healthy"}
    expected_profit = max(revenue * 0.04, 10000.0)
    required_capital = max(revenue * 0.12, 25000.0)
    confidence = 0.66
    metadata = {
        "snapshot": snapshot,
        "required_capital": required_capital,
        "confidence": confidence,
        "score": _compute_score(expected_profit, "low", confidence, required_capital),
        "approval_required": False,
    }
    oid = _insert_opportunity(
        user_id=int(user_id),
        opp_type="business",
        title="Improve margin using cost optimization",
        description="Business margin below threshold; optimize procurement and pricing mix.",
        expected_profit=expected_profit,
        risk_level="low",
        metadata_json=metadata,
    )
    if oid is None:
        return {"ok": False, "error": "Unable to persist opportunity"}
    return {"ok": True, "created": True, "opportunity_id": oid}


def detect_price_arbitrage(user_id: int, query: str = "commodity price spread india") -> dict[str, Any]:
    research = run_supplier_research_sync(query)
    if not research.get("ok"):
        return {"ok": False, "error": research.get("error") or "Arbitrage scan failed"}
    suppliers = research.get("suppliers") or []
    if len(suppliers) < 2:
        return {"ok": True, "created": False, "reason": "Insufficient market data"}
    expected_profit = 18000.0
    required_capital = 70000.0
    confidence = 0.58
    metadata = {
        "research": research,
        "required_capital": required_capital,
        "confidence": confidence,
        "score": _compute_score(expected_profit, "high", confidence, required_capital),
        "approval_required": True,
    }
    oid = _insert_opportunity(
        user_id=int(user_id),
        opp_type="arbitrage",
        title="Cross-supplier price arbitrage",
        description="Detected potential buy-low/sell-high spread from supplier research.",
        expected_profit=expected_profit,
        risk_level="high",
        metadata_json=metadata,
    )
    if oid is None:
        return {"ok": False, "error": "Unable to persist opportunity"}
    return {"ok": True, "created": True, "opportunity_id": oid}


def detect_supplier_margin_opportunities(user_id: int, query: str = "industrial raw materials suppliers") -> dict[str, Any]:
    research = run_supplier_research_sync(query)
    if not research.get("ok"):
        return {"ok": False, "error": research.get("error") or "Supplier margin scan failed"}
    expected_profit = 12000.0
    required_capital = 40000.0
    confidence = 0.64
    metadata = {
        "research": research,
        "required_capital": required_capital,
        "confidence": confidence,
        "score": _compute_score(expected_profit, "medium", confidence, required_capital),
        "approval_required": False,
    }
    oid = _insert_opportunity(
        user_id=int(user_id),
        opp_type="business",
        title="Supplier margin uplift opportunity",
        description="Alternative suppliers suggest potential procurement savings.",
        expected_profit=expected_profit,
        risk_level="medium",
        metadata_json=metadata,
    )
    if oid is None:
        return {"ok": False, "error": "Unable to persist opportunity"}
    return {"ok": True, "created": True, "opportunity_id": oid}


def list_opportunities(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 300))
    with factory() as session:
        q: Select[tuple[Opportunity]] = (
            select(Opportunity)
            .where(Opportunity.user_id == int(user_id))
            .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
            .limit(lim)
        )
        rows = session.execute(q).scalars().all()
        out = []
        for r in rows:
            meta = r.metadata_json or {}
            out.append(
                {
                    "id": int(r.id),
                    "type": str(r.type or ""),
                    "title": str(r.title or ""),
                    "description": str(r.description or ""),
                    "expected_profit": float(r.expected_profit or 0),
                    "risk_level": str(r.risk_level or "medium"),
                    "status": str(r.status or "new"),
                    "confidence": float(meta.get("confidence") or 0),
                    "score": float(meta.get("score") or 0),
                    "required_capital": float(meta.get("required_capital") or 0),
                    "metadata_json": meta,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


def _get_opportunity(user_id: int, opportunity_id: int):
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        return session.execute(
            select(Opportunity).where(Opportunity.user_id == int(user_id), Opportunity.id == int(opportunity_id))
        ).scalar_one_or_none()


def approve_opportunity(user_id: int, opportunity_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(Opportunity).where(Opportunity.user_id == int(user_id), Opportunity.id == int(opportunity_id))
        ).scalar_one_or_none()
        if row is None:
            return {"ok": False, "error": "Opportunity not found"}
        row.status = "approved"
        session.commit()
        return {"ok": True, "id": int(row.id), "status": row.status}


def execute_opportunity(user_id: int, organization_id: int, role_name: str, opportunity_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.execute(
            select(Opportunity).where(Opportunity.user_id == int(user_id), Opportunity.id == int(opportunity_id))
        ).scalar_one_or_none()
        if row is None:
            return {"ok": False, "error": "Opportunity not found"}
        mission = create_mission_plan(user_id=int(user_id), command=f"execute opportunity: {row.title}")
        execution = None
        if mission is not None:
            execution = run_mission_sequentially(
                mission_id=int(mission["mission_id"]),
                ctx=MissionExecutionContext(
                    user_id=int(user_id),
                    organization_id=int(organization_id),
                    role_name=str(role_name or "owner"),
                ),
            )
            row.metadata_json = {**(row.metadata_json or {}), "mission_id": mission.get("mission_id")}
        row.status = "executed"
        realized = float(row.expected_profit or 0) * 0.65
        session.add(
            OpportunityProfitLog(
                opportunity_id=int(row.id),
                profit_loss_amount=realized,
                note="Estimated realized P/L after execution",
            )
        )
        session.commit()
        evaluate_rules(
            {
                "user_id": int(user_id),
                "organization_id": int(organization_id),
                "role_name": str(role_name or "owner"),
                "trigger_type": "new_opportunity_executed",
                "payload": {"opportunity_id": int(row.id), "title": row.title, "realized_profit": realized},
            }
        )
        record_outcome(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="opportunity",
            source_id=int(row.id),
            input_data={"title": row.title, "type": row.type, "risk_level": row.risk_level},
            outcome={
                "realized_profit": realized,
                "success": realized >= 0,
                "status": row.status,
                "note": "Opportunity execution outcome",
            },
        )
        update_strategy_profiles(int(user_id))
        return {"ok": True, "id": int(row.id), "status": row.status, "execution": execution, "realized_profit": realized}


def scan_all_opportunities(user_id: int, organization_id: int) -> dict[str, Any]:
    results = [
        scan_trading_opportunities(user_id=int(user_id), symbol="TCS"),
        scan_business_opportunities(user_id=int(user_id), organization_id=int(organization_id)),
        detect_price_arbitrage(user_id=int(user_id)),
        detect_supplier_margin_opportunities(user_id=int(user_id)),
    ]
    created = [r for r in results if r.get("created")]
    return {"ok": True, "scans": results, "created_count": len(created)}


def best_opportunity_today(user_id: int) -> dict[str, Any] | None:
    rows = list_opportunities(user_id=int(user_id), limit=50)
    if not rows:
        return None
    rows.sort(key=lambda x: (float(x.get("score") or 0), float(x.get("expected_profit") or 0)), reverse=True)
    return rows[0]
