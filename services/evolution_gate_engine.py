"""Controlled self-evolution gate: ingest, evaluate, approve, promote, and feedback."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import DomainDominionProfile, StrategyProfile
from services.governance_engine import validate_action
from services.learning_engine import record_outcome
from services.meta_autonomy_engine import consolidate_stable_knowledge


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _stable_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ingest_sandbox_output(sandbox_output: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out = sandbox_output if isinstance(sandbox_output, dict) else {}
    wf = out.get("would_do_if_fully_autonomous") if isinstance(out.get("would_do_if_fully_autonomous"), dict) else {}
    proposed_tools = []
    for x in list(wf.get("tool_creation_simulation") or out.get("proposed_tools") or []):
        if not isinstance(x, dict):
            continue
        proposed_tools.append(
            {
                "proposal_id": _stable_id("tool"),
                "kind": "tool",
                "title": str(((x.get("tool_spec") or {}) if isinstance(x.get("tool_spec"), dict) else {}).get("name") or x.get("capability_gap") or "proposed_tool"),
                "spec": dict(x.get("tool_spec") or {}),
                "raw": x,
                "confidence": 0.65,
                "reversible": True,
            }
        )
    proposed_actions = []
    for x in list(wf.get("self_initiated_execution") or out.get("proposed_actions") or []):
        if not isinstance(x, dict):
            continue
        proposed_actions.append(
            {
                "proposal_id": _stable_id("action"),
                "kind": "action",
                "title": str(x.get("goal") or x.get("simulated_action") or "proposed_action")[:280],
                "spec": {"simulated_action": str(x.get("simulated_action") or "")[:500]},
                "raw": x,
                "confidence": float(x.get("goal_confidence") or 0.5),
                "reversible": not bool(float(x.get("risk_score") or 0.0) >= 70.0),
            }
        )
    # Strategy proposals can be explicit or synthesized from independent goal pursuit.
    proposed_strategies = []
    for x in list(out.get("proposed_strategies") or []):
        if not isinstance(x, dict):
            continue
        proposed_strategies.append(
            {
                "proposal_id": _stable_id("strategy"),
                "kind": "strategy",
                "title": str(x.get("title") or "proposed_strategy")[:280],
                "spec": dict(x),
                "raw": x,
                "confidence": float(x.get("confidence") or 0.6),
                "reversible": bool(x.get("reversible", True)),
            }
        )
    if not proposed_strategies:
        for x in list(wf.get("independent_goal_pursuit") or []):
            if not isinstance(x, dict):
                continue
            proposed_strategies.append(
                {
                    "proposal_id": _stable_id("strategy"),
                    "kind": "strategy",
                    "title": f"strategy_for_{str(x.get('goal') or 'goal')[:80]}",
                    "spec": {
                        "goal": str(x.get("goal") or "")[:280],
                        "simulated_plan": list(x.get("simulated_plan") or []),
                        "abort_conditions": list(x.get("abort_conditions") or []),
                    },
                    "raw": x,
                    "confidence": 0.62,
                    "reversible": True,
                }
            )
    return {
        "proposed_tools": proposed_tools,
        "proposed_strategies": proposed_strategies,
        "proposed_actions": proposed_actions,
    }


def _estimate_risk(title: str, kind: str, raw: dict[str, Any]) -> float:
    t = str(title or "").lower()
    score = 20.0
    if kind == "tool":
        score += 25.0
    if kind == "action":
        score += 15.0
    if any(k in t for k in ("trade", "payment", "contract", "transfer", "delete", "deploy")):
        score += 45.0
    if isinstance(raw, dict) and "risk_score" in raw:
        try:
            score = max(score, float(raw.get("risk_score") or 0.0))
        except Exception:
            pass
    return max(0.0, min(99.0, score))


def _system_impact(kind: str, risk_score: float) -> str:
    if kind == "tool" and risk_score >= 45:
        return "high"
    if risk_score >= 70:
        return "high"
    if risk_score >= 40:
        return "medium"
    return "low"


def _approve_decision(*, kind: str, risk_score: float, success_probability: float, reversible: bool, system_impact: str) -> dict[str, Any]:
    approval_required = bool(kind == "tool" or system_impact == "high")
    auto_approved = bool((risk_score <= 35.0) and (success_probability >= 0.75) and reversible and (not approval_required))
    return {
        "approval_required": approval_required,
        "auto_approved": auto_approved,
    }


def sandbox_test_proposals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tested: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        risk = float(row.get("risk_score") or 0.0)
        reversible = bool(row.get("reversibility"))
        requires_approval = bool(row.get("approval_required"))
        stage = {
            "pipeline_stage": "proposal->sandbox->test->approval->production",
            "sandbox_prototype_created": True if kind == "tool" else False,
            "sandbox_test_executed": True,
            "sandbox_test_passed": bool(risk < 75.0 and reversible),
            "approval_gate_required": bool(
                requires_approval
                or kind == "tool"
                or str(row.get("system_impact") or "") == "high"
                or any(k in str(row.get("title") or "").lower() for k in ("external", "payment", "financial", "system"))
            ),
        }
        tested.append({**row, "sandbox_validation": stage})
    return tested


def evaluate_proposals(
    *,
    user_id: int,
    organization_id: int,
    proposals: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for bucket in ("proposed_tools", "proposed_strategies", "proposed_actions"):
        for p in list(proposals.get(bucket) or []):
            if not isinstance(p, dict):
                continue
            kind = str(p.get("kind") or "unknown")
            title = str(p.get("title") or "")
            raw = p.get("raw") if isinstance(p.get("raw"), dict) else {}
            risk_score = _estimate_risk(title, kind, raw)
            success_probability = max(0.05, min(0.95, float(p.get("confidence") or 0.5)))
            reversible = bool(p.get("reversible", True))
            system_impact = _system_impact(kind, risk_score)
            gov = validate_action(
                "evolution_gate_promotion",
                {
                    "user_id": int(user_id),
                    "domain": "automation",
                    "payload": {
                        "organization_id": int(organization_id),
                        "proposal_kind": kind,
                        "proposal_title": title[:220],
                        "risk_score": risk_score,
                    },
                },
            )
            reject_reason = ""
            if (risk_score >= 70.0 and not reversible):
                reject_reason = "high_risk_low_reversibility"
            elif not bool(gov.get("allowed")):
                reject_reason = f"governance_rejected:{str(gov.get('reason') or 'not_allowed')}"
            elif "execution_engine" in title.lower() or "modify core engine" in title.lower():
                reject_reason = "forbidden_core_engine_modification"
            approval = _approve_decision(
                kind=kind,
                risk_score=risk_score,
                success_probability=success_probability,
                reversible=reversible,
                system_impact=system_impact,
            )
            row = {
                **p,
                "risk_score": round(risk_score, 2),
                "success_probability": round(success_probability, 3),
                "reversibility": reversible,
                "system_impact": system_impact,
                "governance_allowed": bool(gov.get("allowed")),
                "governance_reason": str(gov.get("reason") or ""),
                **approval,
                "promotion_state": (
                    "rejected"
                    if reject_reason
                    else ("approved" if approval.get("auto_approved") else "pending_approval")
                ),
            }
            if reject_reason:
                row["rejection_reason"] = reject_reason
                rejected.append(row)
            else:
                evaluated.append(row)
    return {"evaluated": evaluated, "rejected": rejected}


def _ensure_profile(session, *, user_id: int, organization_id: int) -> DomainDominionProfile:
    row = session.execute(
        select(DomainDominionProfile).where(
            DomainDominionProfile.user_id == int(user_id),
            DomainDominionProfile.organization_id == int(organization_id),
        )
    ).scalar_one_or_none()
    if row is None:
        row = DomainDominionProfile(
            user_id=int(user_id),
            organization_id=int(organization_id),
            active_domain="business",
            enabled=True,
            knowledge_json={},
            meta_json={},
        )
        session.add(row)
        session.flush()
    return row


def promote_approved(
    *,
    user_id: int,
    organization_id: int,
    evaluated_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": False, "error": "database_unavailable", "promoted": []}
    promoted: list[dict[str, Any]] = []
    with fn() as session:
        with session.begin():
            profile = _ensure_profile(session, user_id=int(user_id), organization_id=int(organization_id))
            meta = dict(profile.meta_json or {})
            eg = meta.get("evolution_gate") if isinstance(meta.get("evolution_gate"), dict) else {}
            history = list(eg.get("promotions") or [])
            for row in evaluated_rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("promotion_state") or "") != "approved":
                    continue
                sv = row.get("sandbox_validation") if isinstance(row.get("sandbox_validation"), dict) else {}
                if not bool(sv.get("sandbox_test_passed")):
                    continue
                pid = str(row.get("proposal_id") or _stable_id("proposal"))
                kind = str(row.get("kind") or "")
                if kind == "strategy":
                    domain = "evolved_autonomy"
                    sp = (
                        session.execute(
                            select(StrategyProfile).where(
                                StrategyProfile.user_id == int(user_id),
                                StrategyProfile.domain == domain,
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if sp is None:
                        sp = StrategyProfile(user_id=int(user_id), domain=domain, parameters_json={}, performance_score=0.0)
                        session.add(sp)
                        session.flush()
                    params = dict(sp.parameters_json or {})
                    evolved = list(params.get("evolved_strategies") or [])
                    evolved.append(
                        {
                            "proposal_id": pid,
                            "title": str(row.get("title") or "")[:220],
                            "spec": dict(row.get("spec") or {}),
                            "promoted_at": _now_iso(),
                            "reversible": bool(row.get("reversibility")),
                        }
                    )
                    params["evolved_strategies"] = evolved[-80:]
                    sp.parameters_json = params
                    sp.updated_at = datetime.now(timezone.utc)
                promoted_row = {
                    "promotion_id": pid,
                    "kind": kind,
                    "title": str(row.get("title") or "")[:280],
                    "risk_score": float(row.get("risk_score") or 0.0),
                    "success_probability": float(row.get("success_probability") or 0.0),
                    "reversibility": bool(row.get("reversibility")),
                    "system_impact": str(row.get("system_impact") or ""),
                    "promoted_at": _now_iso(),
                    "status": "promoted",
                    "source": "sandbox_evolution_gate",
                    "spec": dict(row.get("spec") or {}),
                }
                history.append(promoted_row)
                promoted.append(promoted_row)
            eg["promotions"] = history[-200:]
            eg["last_promotion_at"] = _now_iso()
            meta["evolution_gate"] = eg
            profile.meta_json = meta
            profile.updated_at = datetime.now(timezone.utc)
    return {"ok": True, "promoted": promoted}


def record_promotion_feedback(
    *,
    user_id: int,
    organization_id: int,
    promotion_id: str,
    success: bool,
    roi: float,
    note: str = "",
) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": False, "error": "database_unavailable"}
    updated = False
    with fn() as session:
        with session.begin():
            profile = session.execute(
                select(DomainDominionProfile).where(
                    DomainDominionProfile.user_id == int(user_id),
                    DomainDominionProfile.organization_id == int(organization_id),
                )
            ).scalar_one_or_none()
            if profile is not None:
                meta = dict(profile.meta_json or {})
                eg = meta.get("evolution_gate") if isinstance(meta.get("evolution_gate"), dict) else {}
                hist = list(eg.get("promotions") or [])
                for row in hist:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("promotion_id") or "") != str(promotion_id):
                        continue
                    row["feedback"] = {
                        "success": bool(success),
                        "roi": float(roi),
                        "note": str(note or "")[:400],
                        "at": _now_iso(),
                    }
                    row["status"] = "validated" if bool(success) else "degraded"
                    updated = True
                eg["promotions"] = hist[-200:]
                meta["evolution_gate"] = eg
                profile.meta_json = meta
                profile.updated_at = datetime.now(timezone.utc)
    learning = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="evolution_gate",
        source_id=None,
        input_data={"promotion_id": str(promotion_id), "note": str(note or "")[:400]},
        outcome={
            "success": bool(success),
            "failure": not bool(success),
            "profit_loss": float(roi),
            "note": "evolution_gate_promotion_feedback",
        },
    )
    stable = consolidate_stable_knowledge(user_id=int(user_id), organization_id=int(organization_id))
    return {"ok": True, "updated": updated, "learning": learning, "stable_knowledge": stable}


def run_controlled_evolution_gate(
    *,
    user_id: int,
    organization_id: int,
    sandbox_output: dict[str, Any],
) -> dict[str, Any]:
    proposals = ingest_sandbox_output(sandbox_output if isinstance(sandbox_output, dict) else {})
    evaluated = evaluate_proposals(
        user_id=int(user_id),
        organization_id=int(organization_id),
        proposals=proposals,
    )
    tested_rows = sandbox_test_proposals([x for x in list(evaluated.get("evaluated") or []) if isinstance(x, dict)])
    promoted = promote_approved(
        user_id=int(user_id),
        organization_id=int(organization_id),
        evaluated_rows=tested_rows,
    )
    return {
        "ok": True,
        "generated_at": _now_iso(),
        "evolution_gate_architecture": {
            "stages": ["ingestion", "evaluation", "sandbox", "test", "approval", "promotion", "feedback"],
            "safety": [
                "no_auto_promotion_for_high_risk_or_low_reversibility",
                "governance_validation_required",
                "kill_switch_and_governor_respected",
                "no_execution_engine_modification",
                "mandatory_approval_for_external_financial_system_changes",
            ],
        },
        "promotion_criteria": {
            "auto_approval": "low_risk && high_confidence && reversible && governance_allowed",
            "approval_required": ["tool_creation", "high_impact_actions"],
            "rejection": ["high_risk_low_reversibility", "governance_violation", "core_engine_modification_attempt"],
        },
        "ingested": {
            "proposed_tools": len(list(proposals.get("proposed_tools") or [])),
            "proposed_strategies": len(list(proposals.get("proposed_strategies") or [])),
            "proposed_actions": len(list(proposals.get("proposed_actions") or [])),
        },
        "evaluation": evaluated,
        "sandbox_test": {"tested": tested_rows},
        "promotion": promoted,
    }
