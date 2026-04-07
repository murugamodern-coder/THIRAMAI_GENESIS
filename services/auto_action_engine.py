from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, func, select

from core.database import get_session_factory
from core.db.models import AiDecision, AuditLog, AutonomyFeedback, ControlPlaneAlert, Organization
from services import approval_service
from services.policy_engine import load_autonomy_policy, policy_allows_auto_approve

_log = logging.getLogger("thiramai.auto_action_engine")


def _confidence_from_payload(payload: dict[str, Any]) -> float:
    c = payload.get("confidence")
    try:
        if c is None:
            return 0.5
        v = float(c)
        return max(0.0, min(1.0, v))
    except Exception:
        return 0.5


def _risk_bucket(row: AiDecision) -> str:
    # low: does not require approval and low priority
    if not bool(row.requires_approval) and (row.priority or "").lower() == "low":
        return "low"
    # high: explicitly high priority or requires approval
    if (row.priority or "").lower() == "high" or bool(row.requires_approval):
        return "high"
    return "medium"


def _alert(session, *, organization_id: int, severity: str, type_: str, message: str) -> None:
    a = ControlPlaneAlert(
        organization_id=int(organization_id),
        type=type_[:64],
        message=message[:4000],
        severity=severity[:16],
        resolved=False,
    )
    session.add(a)


def _record_feedback(
    session,
    *,
    organization_id: int,
    decision_id: int | None,
    action_type: str,
    outcome: str,
    confidence: float | None,
    notes: str | None = None,
) -> None:
    fb = AutonomyFeedback(
        organization_id=int(organization_id),
        user_id=None,
        decision_id=int(decision_id) if decision_id else None,
        action_type=action_type[:128],
        outcome=outcome[:32],
        confidence=confidence,
        notes=(notes or None),
    )
    session.add(fb)


def _policy_snapshot(policy) -> dict[str, Any]:
    try:
        return {
            "auto_mode_enabled": bool(getattr(policy, "auto_mode_enabled", False)),
            "thresholds": {
                "high": float(getattr(policy, "confidence_high_threshold", 0.0)),
                "medium": float(getattr(policy, "confidence_medium_threshold", 0.0)),
            },
            "autoApprove": dict(getattr(policy, "auto_approve", {}) or {}),
        }
    except Exception:
        return {}


def _audit_auto_action(
    session,
    *,
    organization_id: int,
    decision_id: int,
    entity: str,
    result: str,
    confidence: float,
    rules_applied: list[str],
    reason: str,
    policy_snapshot: dict[str, Any],
) -> None:
    """
    Persist explainability + auditability for autonomous actions.
    """
    row = AuditLog(
        organization_id=int(organization_id),
        user_id=None,
        action_type="AUTO_ACTION",
        entity=str(entity or "")[:128] or "ai_decision",
        entity_id=str(decision_id)[:128],
        source="AI",
        result=str(result)[:16],
        audit_metadata={
            "confidence": float(confidence),
            "rules_applied": rules_applied,
            "reason": str(reason)[:2000],
            "policy_snapshot": policy_snapshot,
        },
    )
    session.add(row)


def run_autonomy_cycle_for_org(*, organization_id: int, limit: int = 20) -> dict[str, Any]:
    """
    Evaluate pending ai_decisions and auto-resolve when policy permits.
    """
    oid = int(organization_id)
    policy = load_autonomy_policy(organization_id=oid)
    if not policy.auto_mode_enabled:
        return {"ok": True, "organization_id": oid, "auto_mode": False, "processed": 0}

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    processed = 0
    executed = 0
    alerted = 0

    with factory() as session:
        # org kill switch / safety
        org = session.get(Organization, oid)
        if org is None or bool(getattr(org, "is_disabled", False)):
            return {"ok": True, "organization_id": oid, "auto_mode": False, "processed": 0}

        try:
            rows = list(
                session.scalars(
                    select(AiDecision)
                    .where(AiDecision.organization_id == oid, AiDecision.status == "pending")
                    .order_by(desc(AiDecision.id))
                    .limit(max(1, min(int(limit), 200)))
                ).all()
            )
        except Exception as exc:
            # Some deployments may not have Phase-3 ai_decisions persistence enabled.
            _log.warning("autonomy: ai_decisions unavailable for org=%s (%s)", oid, exc)
            return {"ok": True, "organization_id": oid, "auto_mode": True, "processed": 0, "executed": 0, "alerts_created": 0}

    # Resolve outside the DB session blocks as approval_service opens its own sessions.
    for r in rows:
        processed += 1
        payload = dict(r.payload) if isinstance(r.payload, dict) else {}
        action = str(r.action or "")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        conf = _confidence_from_payload(payload)
        risk = _risk_bucket(r)
        pol_snap = _policy_snapshot(policy)
        rules_common = [f"risk_bucket:{risk}", f"priority:{(r.priority or '').lower()}", f"requires_approval:{bool(r.requires_approval)}"]

        # high-risk routing
        if risk == "high":
            allow, why = policy_allows_auto_approve(policy=policy, action=action, payload=data)
            if conf >= policy.confidence_high_threshold and allow:
                rules = rules_common + [
                    f"confidence>={policy.confidence_high_threshold:.2f}",
                    "policy:autoApprove:allow",
                ]
                out = approval_service.resolve_ai_decision(
                    decision_id=int(r.id),
                    organization_id=oid,
                    resolve_status="approved",
                    resolver_user_id=None,
                    resolver_role_name="owner",
                )
                ok = bool(out.get("ok"))
                if ok:
                    executed += 1
                    with factory() as session:
                        with session.begin():
                            _record_feedback(
                                session,
                                organization_id=oid,
                                decision_id=int(r.id),
                                action_type=action,
                                outcome="succeeded",
                                confidence=conf,
                                notes="auto-approved high-risk via policy",
                            )
                            _audit_auto_action(
                                session,
                                organization_id=oid,
                                decision_id=int(r.id),
                                entity=action,
                                result="SUCCESS",
                                confidence=conf,
                                rules_applied=rules,
                                reason="auto_approved_high_risk",
                                policy_snapshot=pol_snap,
                            )
                else:
                    with factory() as session:
                        with session.begin():
                            _record_feedback(
                                session,
                                organization_id=oid,
                                decision_id=int(r.id),
                                action_type=action,
                                outcome="failed",
                                confidence=conf,
                                notes=str(out.get("error") or why or "execution_failed")[:2000],
                            )
                            _audit_auto_action(
                                session,
                                organization_id=oid,
                                decision_id=int(r.id),
                                entity=action,
                                result="BLOCKED",
                                confidence=conf,
                                rules_applied=rules,
                                reason=str(out.get("error") or "execution_failed"),
                                policy_snapshot=pol_snap,
                            )
                continue

            # otherwise require admin approval: alert + leave pending
            with factory() as session:
                with session.begin():
                    _alert(
                        session,
                        organization_id=oid,
                        severity="critical",
                        type_="autonomy_requires_approval",
                        message=f"Pending ADMIN approval: decision_id={int(r.id)} action={action} priority={r.priority} confidence={conf:.2f}",
                    )
                    _record_feedback(
                        session,
                        organization_id=oid,
                        decision_id=int(r.id),
                        action_type=action,
                        outcome="overridden",
                        confidence=conf,
                        notes=f"blocked_or_requires_approval:{why or 'no_policy'}",
                    )
                    _audit_auto_action(
                        session,
                        organization_id=oid,
                        decision_id=int(r.id),
                        entity=action,
                        result="BLOCKED",
                        confidence=conf,
                        rules_applied=rules_common
                        + [
                            f"confidence<{policy.confidence_high_threshold:.2f}" if conf < policy.confidence_high_threshold else "confidence_ok",
                            f"policy:{why or 'no_policy'}",
                        ],
                        reason="requires_admin_approval",
                        policy_snapshot=pol_snap,
                    )
                    alerted += 1
            continue

        # medium-risk: notify operator unless very high confidence
        if risk == "medium" and conf < policy.confidence_medium_threshold:
            with factory() as session:
                with session.begin():
                    _alert(
                        session,
                        organization_id=oid,
                        severity="warning",
                        type_="autonomy_operator_review",
                        message=f"Operator review suggested: decision_id={int(r.id)} action={action} confidence={conf:.2f}",
                    )
                    _audit_auto_action(
                        session,
                        organization_id=oid,
                        decision_id=int(r.id),
                        entity=action,
                        result="BLOCKED",
                        confidence=conf,
                        rules_applied=rules_common + [f"confidence<{policy.confidence_medium_threshold:.2f}", "operator_review"],
                        reason="operator_review_suggested",
                        policy_snapshot=pol_snap,
                    )
                    alerted += 1
            continue

        # low-risk: auto-execute if confidence sufficiently high OR requires_approval is false
        if conf >= policy.confidence_medium_threshold or not bool(r.requires_approval):
            rules = rules_common + [f"confidence>={policy.confidence_medium_threshold:.2f}" if conf >= policy.confidence_medium_threshold else "requires_approval:false"]
            out = approval_service.resolve_ai_decision(
                decision_id=int(r.id),
                organization_id=oid,
                resolve_status="approved",
                resolver_user_id=None,
                resolver_role_name="owner",
            )
            ok = bool(out.get("ok"))
            with factory() as session:
                with session.begin():
                    _record_feedback(
                        session,
                        organization_id=oid,
                        decision_id=int(r.id),
                        action_type=action,
                        outcome="succeeded" if ok else "failed",
                        confidence=conf,
                        notes="auto-executed low/medium" if ok else str(out.get("error") or "execution_failed"),
                    )
                    _audit_auto_action(
                        session,
                        organization_id=oid,
                        decision_id=int(r.id),
                        entity=action,
                        result="SUCCESS" if ok else "BLOCKED",
                        confidence=conf,
                        rules_applied=rules,
                        reason="auto_executed" if ok else str(out.get("error") or "execution_failed"),
                        policy_snapshot=pol_snap,
                    )
            if ok:
                executed += 1
            continue

    # anomaly detection: spike of failures in last hour
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        with factory() as session:
            failed = session.scalar(
                select(func.count()).select_from(AiDecision).where(
                    and_(
                        AiDecision.organization_id == oid,
                        AiDecision.status == "failed",
                        AiDecision.created_at >= cutoff,
                    )
                )
            )
            total = session.scalar(
                select(func.count()).select_from(AiDecision).where(
                    and_(AiDecision.organization_id == oid, AiDecision.created_at >= cutoff)
                )
            )
            failed_n = int(failed or 0)
            total_n = int(total or 0)
            if total_n >= 6 and failed_n / max(1, total_n) >= 0.5:
                with session.begin():
                    _alert(
                        session,
                        organization_id=oid,
                        severity="critical",
                        type_="anomaly_failure_spike",
                        message=f"Anomaly detected: {failed_n}/{total_n} AI decisions failed in last hour.",
                    )
    except Exception:
        pass

    return {
        "ok": True,
        "organization_id": oid,
        "auto_mode": True,
        "processed": processed,
        "executed": executed,
        "alerts_created": alerted,
    }


def run_autonomy_cycle_for_all_orgs(limit_per_org: int = 20) -> dict[str, Any]:
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        org_ids = list(session.scalars(select(Organization.id)).all())
    out = []
    for oid in org_ids:
        try:
            out.append(run_autonomy_cycle_for_org(organization_id=int(oid), limit=limit_per_org))
        except Exception as exc:
            _log.warning("autonomy_cycle_failed org=%s err=%s", oid, exc)
    return {"ok": True, "organizations": len(org_ids), "results": out}

