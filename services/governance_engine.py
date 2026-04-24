"""Governance, safety, and control layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.db.session_utils import get_session_factory_safe
from core.db.models import ExecutionAuditLog, Guardrail


def _session_factory_or_none():
    return get_session_factory_safe()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_guardrails(user_id: int) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        rows = (
            session.execute(
                select(Guardrail).where(Guardrail.user_id == int(user_id)).order_by(Guardrail.created_at.desc(), Guardrail.id.desc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(r.id),
                "rule_name": str(r.rule_name or ""),
                "domain": str(r.domain or ""),
                "condition_json": r.condition_json or {},
                "action_limit_json": r.action_limit_json or {},
                "enabled": bool(r.enabled),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def upsert_guardrail(
    *,
    user_id: int,
    guardrail_id: int | None,
    rule_name: str,
    domain: str,
    condition_json: dict[str, Any],
    action_limit_json: dict[str, Any],
    enabled: bool,
) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        normalized_rule = str(rule_name or "guardrail").strip()[:120]
        normalized_domain = str(domain or "automation").strip().lower()[:32]
        values = {
            "user_id": int(user_id),
            "rule_name": normalized_rule,
            "domain": normalized_domain,
            "condition_json": condition_json or {},
            "action_limit_json": action_limit_json or {},
            "enabled": bool(enabled),
        }

        if guardrail_id:
            row = session.execute(
                select(Guardrail).where(Guardrail.id == int(guardrail_id), Guardrail.user_id == int(user_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            row.rule_name = normalized_rule
            row.domain = normalized_domain
            row.condition_json = values["condition_json"]
            row.action_limit_json = values["action_limit_json"]
            row.enabled = bool(values["enabled"])
            session.commit()
            return {"id": int(row.id)}

        # UPSERT path: one row per (user_id, rule_name, domain).
        dialect = str(session.bind.dialect.name).lower() if session.bind is not None else ""
        if dialect == "postgresql":
            stmt = (
                pg_insert(Guardrail)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["user_id", "rule_name", "domain"],
                    set_={
                        "condition_json": values["condition_json"],
                        "action_limit_json": values["action_limit_json"],
                        "enabled": values["enabled"],
                    },
                )
            )
            session.execute(stmt)
            session.commit()
        elif dialect == "sqlite":
            stmt = (
                sqlite_insert(Guardrail)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["user_id", "rule_name", "domain"],
                    set_={
                        "condition_json": values["condition_json"],
                        "action_limit_json": values["action_limit_json"],
                        "enabled": values["enabled"],
                    },
                )
            )
            session.execute(stmt)
            session.commit()
        else:
            row = session.execute(
                select(Guardrail).where(
                    Guardrail.user_id == int(user_id),
                    Guardrail.rule_name == normalized_rule,
                    Guardrail.domain == normalized_domain,
                )
            ).scalar_one_or_none()
            if row is None:
                row = Guardrail(user_id=int(user_id))
                session.add(row)
            row.rule_name = normalized_rule
            row.domain = normalized_domain
            row.condition_json = values["condition_json"]
            row.action_limit_json = values["action_limit_json"]
            row.enabled = bool(values["enabled"])
            session.commit()
        row = session.execute(
            select(Guardrail).where(
                Guardrail.user_id == int(user_id),
                Guardrail.rule_name == normalized_rule,
                Guardrail.domain == normalized_domain,
            )
        ).scalar_one_or_none()
        return {"id": int(row.id)} if row is not None else None


def is_kill_switch_active(user_id: int) -> bool:
    factory = _session_factory_or_none()
    if factory is None:
        # Fail closed for production safety when governance storage is unavailable.
        return True
    with factory() as session:
        row = session.execute(
            select(Guardrail).where(
                Guardrail.user_id == int(user_id),
                Guardrail.rule_name == "global_kill_switch",
                Guardrail.domain == "global",
                Guardrail.enabled.is_(True),
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        limits = row.action_limit_json if isinstance(row.action_limit_json, dict) else {}
        return bool(limits.get("kill_switch") is True)


def log_execution(
    *,
    user_id: int,
    action_type: str,
    source: str,
    payload_json: dict[str, Any] | None,
    result_json: dict[str, Any] | None,
    status: str,
    execution_id: str | None = None,
    reasoning_summary: str | None = None,
    why_action_taken: str | None = None,
    data_influenced_json: dict[str, Any] | None = None,
) -> None:
    factory = _session_factory_or_none()
    if factory is None:
        return
    with factory() as session:
        session.add(
            ExecutionAuditLog(
                user_id=int(user_id),
                action_type=str(action_type or "")[:64],
                source=str(source or "")[:32],
                payload_json=payload_json or {},
                execution_id=(execution_id or "").strip()[:120] or None,
                reasoning_summary=str(reasoning_summary)[:2000] if reasoning_summary else None,
                why_action_taken=str(why_action_taken)[:4000] if why_action_taken else None,
                data_influenced_json=data_influenced_json or {},
                result_json=result_json or {},
                status=str(status or "success")[:32],
            )
        )
        session.commit()


def _recent_logs(session, user_id: int, *, action_type: str | None = None, source: str | None = None, hours: int = 24):
    since = _now() - timedelta(hours=max(1, int(hours)))
    q: Select[tuple[ExecutionAuditLog]] = (
        select(ExecutionAuditLog)
        .where(ExecutionAuditLog.user_id == int(user_id), ExecutionAuditLog.created_at >= since)
        .order_by(ExecutionAuditLog.created_at.desc(), ExecutionAuditLog.id.desc())
    )
    if action_type:
        q = q.where(ExecutionAuditLog.action_type == str(action_type))
    if source:
        q = q.where(ExecutionAuditLog.source == str(source))
    return session.execute(q).scalars().all()


def enforce_limits(
    *,
    user_id: int,
    action_type: str,
    domain: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "allowed": False, "reason": "Database unavailable"}
    with factory() as session:
        pred_risk_level = "medium"
        try:
            from services.predictive_engine import predict_risk_spike

            pred_risk_level = str((predict_risk_spike(int(user_id)).get("risk_level") or "medium")).lower()
        except Exception:
            pred_risk_level = "medium"
        rules = (
            session.execute(
                select(Guardrail).where(
                    Guardrail.user_id == int(user_id),
                    Guardrail.enabled.is_(True),
                    Guardrail.domain.in_([str(domain), "global", "system"]),
                )
            )
            .scalars()
            .all()
        )
        for rule in rules:
            limits = rule.action_limit_json or {}
            if limits.get("kill_switch") is True:
                return {"ok": True, "allowed": False, "reason": f"Kill switch enabled by {rule.rule_name}"}

            if action_type in {"trade_buy", "trade_sell", "trade"}:
                max_trade = float(limits.get("max_trade_amount_per_day") or 0)
                if max_trade > 0 and pred_risk_level == "high":
                    max_trade = max_trade * 0.6
                if max_trade > 0:
                    today_logs = _recent_logs(session, int(user_id), action_type=action_type, hours=24)
                    total = 0.0
                    for lg in today_logs:
                        p = lg.payload_json or {}
                        total += float(p.get("trade_amount") or 0)
                    next_amt = float(payload.get("trade_amount") or 0)
                    if total + next_amt > max_trade:
                        return {"ok": True, "allowed": False, "reason": f"Daily trade amount limit exceeded ({max_trade})"}

                max_loss = float(limits.get("max_loss_threshold") or 0)
                if max_loss > 0 and pred_risk_level == "high":
                    max_loss = max_loss * 0.75
                if max_loss > 0:
                    today_logs = _recent_logs(session, int(user_id), action_type=action_type, hours=24)
                    losses = 0.0
                    for lg in today_logs:
                        r = lg.result_json or {}
                        pnl = float(r.get("realized_pnl") or r.get("realized_profit") or r.get("profit_loss") or 0)
                        if pnl < 0:
                            losses += abs(pnl)
                    if losses >= max_loss:
                        return {"ok": True, "allowed": False, "reason": f"Max loss threshold reached ({max_loss})"}

            if action_type in {"send_email", "notify_user"}:
                max_emails = int(limits.get("max_emails_per_hour") or 0)
                if max_emails > 0 and pred_risk_level == "high":
                    max_emails = max(1, int(max_emails * 0.7))
                if max_emails > 0:
                    hour_logs = _recent_logs(session, int(user_id), action_type="send_email", hours=1)
                    if len(hour_logs) >= max_emails:
                        return {"ok": True, "allowed": False, "reason": f"Max emails per hour exceeded ({max_emails})"}
    return {"ok": True, "allowed": True}


def _circuit_breaker_check(user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "allowed": False, "reason": "Database unavailable"}
    with factory() as session:
        logs = _recent_logs(session, int(user_id), hours=1)
        failures = [x for x in logs if str(x.status or "").lower() in {"failed", "error", "blocked"}]
        if len(failures) >= 5:
            return {"ok": True, "allowed": False, "reason": "Circuit breaker: repeated failures detected"}
    return {"ok": True, "allowed": True}


def validate_action(action: str, context: dict[str, Any]) -> dict[str, Any]:
    from services.autonomy_safety_layer import global_autonomy_halted

    if global_autonomy_halted():
        return {
            "ok": True,
            "allowed": False,
            "reason": "Global autonomy halt is active (emergency stop)",
        }
    user_id = int(context.get("user_id") or 0)
    if user_id <= 0:
        return {"ok": False, "allowed": False, "reason": "Invalid user context"}
    if _session_factory_or_none() is None:
        return {
            "ok": False,
            "allowed": False,
            "reason": "governance_unavailable_fail_closed",
        }
    if is_kill_switch_active(int(user_id)):
        return {"ok": True, "allowed": False, "reason": "Kill switch enabled"}
    domain = str(context.get("domain") or "automation")
    payload = context.get("payload") if isinstance(context.get("payload"), dict) else {}
    circuit = _circuit_breaker_check(user_id)
    if not circuit.get("allowed"):
        return circuit
    limits = enforce_limits(user_id=user_id, action_type=str(action), domain=domain, payload=payload)
    if not limits.get("allowed"):
        return limits
    return {"ok": True, "allowed": True}


def set_kill_switch(user_id: int, enabled: bool, reason: str = "") -> dict[str, Any] | None:
    return upsert_guardrail(
        user_id=int(user_id),
        guardrail_id=None,
        rule_name="global_kill_switch",
        domain="global",
        condition_json={"reason": str(reason or "")[:300]},
        action_limit_json={"kill_switch": bool(enabled)},
        enabled=True,
    )


def list_execution_logs(user_id: int, limit: int = 150) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"items": [], "summary": {}}
    lim = max(1, min(int(limit), 500))
    with factory() as session:
        rows = (
            session.execute(
                select(ExecutionAuditLog)
                .where(ExecutionAuditLog.user_id == int(user_id))
                .order_by(ExecutionAuditLog.created_at.desc(), ExecutionAuditLog.id.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": int(r.id),
                "execution_id": str(r.execution_id or "") if r.execution_id else None,
                "action_type": str(r.action_type or ""),
                "source": str(r.source or ""),
                "payload_json": r.payload_json or {},
                "reasoning_summary": str(r.reasoning_summary or "") if r.reasoning_summary else None,
                "why_action_taken": str(r.why_action_taken or "") if r.why_action_taken else None,
                "data_influenced_json": r.data_influenced_json or {},
                "result_json": r.result_json or {},
                "status": str(r.status or ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        daily_logs = _recent_logs(session, int(user_id), hours=24)
        daily_usage = len(daily_logs)
        risk_exposure = 0.0
        for lg in daily_logs:
            result = lg.result_json or {}
            risk_exposure += abs(float(result.get("realized_pnl") or result.get("profit_loss") or 0))
        return {"items": items, "summary": {"daily_usage": daily_usage, "risk_exposure": round(risk_exposure, 2)}}
