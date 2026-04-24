"""Rule-based automation evaluation and action execution."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select

from core.database import get_session_factory
from core.db.models import AutomationLog, AutomationRule
from services.execute_mission_store import create_mission_plan, run_mission_sequentially, MissionExecutionContext
from services.governance_engine import log_execution, validate_action
from services.integration_engine import notify_user, send_email, send_whatsapp
from services.learning_engine import record_outcome, update_strategy_profiles


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def _match_condition(condition: dict[str, Any], event_payload: dict[str, Any]) -> bool:
    min_value = _num(condition.get("min_value"))
    max_value = _num(condition.get("max_value"))
    field = str(condition.get("field") or "").strip()
    equals = condition.get("equals")
    contains = str(condition.get("contains") or "").strip().lower()
    value = event_payload.get(field) if field else None
    n = _num(value)
    if min_value is not None and (n is None or n < min_value):
        return False
    if max_value is not None and (n is None or n > max_value):
        return False
    if equals is not None and value != equals:
        return False
    if contains and contains not in str(value or "").lower():
        return False
    return True


def _log_action(
    *,
    session,
    user_id: int,
    rule_id: int | None,
    trigger_type: str,
    event_payload: dict[str, Any],
    action_taken: str,
    action_result: dict[str, Any],
) -> None:
    session.add(
        AutomationLog(
            user_id=int(user_id),
            rule_id=int(rule_id) if rule_id else None,
            trigger_type=str(trigger_type or ""),
            event_json=event_payload or {},
            action_taken=str(action_taken or ""),
            action_result_json=action_result or {},
        )
    )


def evaluate_rules(event: dict[str, Any]) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable", "matches": []}
    user_id = int(event.get("user_id") or 0)
    trigger_type = str(event.get("trigger_type") or "").strip()
    if user_id <= 0 or not trigger_type:
        return {"ok": False, "error": "Invalid event payload", "matches": []}
    event_payload = event.get("payload")
    if not isinstance(event_payload, dict):
        event_payload = {}

    with factory() as session:
        q: Select[tuple[AutomationRule]] = select(AutomationRule).where(
            AutomationRule.user_id == int(user_id),
            AutomationRule.enabled.is_(True),
            AutomationRule.trigger_type == trigger_type,
        )
        rules = session.execute(q).scalars().all()
        matches: list[dict[str, Any]] = []
        for rule in rules:
            condition = rule.condition_json or {}
            if not _match_condition(condition, event_payload):
                continue
            action_cfg = rule.action_config_json or {}
            needs_approval = bool(action_cfg.get("require_approval"))
            action_type = str(rule.action_type or "").strip().lower()
            governance = validate_action(
                action_type or "automation_action",
                {
                    "user_id": int(user_id),
                    "domain": "automation",
                    "payload": {"trigger_type": trigger_type, "rule_id": int(rule.id), "action_config": action_cfg},
                },
            )
            if not governance.get("allowed"):
                action_taken = "blocked"
                action_result = {"ok": False, "blocked": True, "reason": governance.get("reason") or "Governance blocked"}
                _log_action(
                    session=session,
                    user_id=int(user_id),
                    rule_id=int(rule.id),
                    trigger_type=trigger_type,
                    event_payload=event_payload,
                    action_taken=action_taken,
                    action_result=action_result,
                )
                log_execution(
                    user_id=int(user_id),
                    action_type=action_type or "automation_action",
                    source="automation",
                    payload_json={"rule_id": int(rule.id), "trigger_type": trigger_type, "event_payload": event_payload},
                    result_json=action_result,
                    status="blocked",
                    execution_id=f"automation_{int(rule.id)}",
                    reasoning_summary="Automation action blocked by governance.",
                    why_action_taken=f"Rule '{rule.name}' matched trigger '{trigger_type}' but was denied by limits.",
                    data_influenced_json={"trigger_type": trigger_type, "rule_id": int(rule.id), "condition": rule.condition_json or {}},
                )
                matches.append(
                    {
                        "rule_id": int(rule.id),
                        "rule_name": str(rule.name or ""),
                        "action_type": str(rule.action_type or ""),
                        "action_taken": action_taken,
                        "result": action_result,
                    }
                )
                continue
            action_result: dict[str, Any] = {}
            action_taken = "executed"
            if action_type in {"send_email", "email"}:
                action_taken = "send_email"
                action_result = send_email(
                    int(user_id),
                    to=str(action_cfg.get("to") or ""),
                    subject=str(action_cfg.get("subject") or f"Rule triggered: {rule.name}"),
                    body=str(action_cfg.get("body") or f"Trigger={trigger_type}, payload={event_payload}"),
                )
            elif action_type in {"send_whatsapp", "whatsapp"}:
                action_taken = "send_whatsapp"
                action_result = send_whatsapp(
                    int(user_id),
                    number=str(action_cfg.get("number") or ""),
                    message=str(action_cfg.get("message") or f"Rule triggered: {rule.name}"),
                )
            elif action_type in {"notify", "notify_user"}:
                action_taken = "notify_user"
                action_result = notify_user(
                    int(user_id),
                    message=str(action_cfg.get("message") or f"Rule triggered: {rule.name}"),
                    subject=str(action_cfg.get("subject") or "Thiramai Automation Alert"),
                )
            else:
                mission_title = str(action_cfg.get("mission_title") or rule.name or "Automation mission").strip()
                mission_prompt = str(action_cfg.get("mission_prompt") or f"{rule.action_type}: {rule.name}").strip()
                mission = create_mission_plan(user_id=int(user_id), command=mission_prompt)
                if mission is None:
                    result = {"ok": False, "error": "Mission create failed"}
                    _log_action(
                        session=session,
                        user_id=int(user_id),
                        rule_id=int(rule.id),
                        trigger_type=trigger_type,
                        event_payload=event_payload,
                        action_taken="mission_create_failed",
                        action_result=result,
                    )
                    matches.append({"rule_id": int(rule.id), "action": "failed", "result": result})
                    continue
                action_result = {
                    "mission_id": mission.get("mission_id"),
                    "mission_title": mission_title,
                    "approval_required": needs_approval,
                }
                action_taken = "approval_required"
                if not needs_approval:
                    action_taken = "auto_executed"
                    action_result["execution"] = run_mission_sequentially(
                        mission_id=int(mission["mission_id"]),
                        ctx=MissionExecutionContext(
                            user_id=int(user_id),
                            organization_id=int(event.get("organization_id") or 0),
                            role_name=str(event.get("role_name") or "owner"),
                        ),
                    )
            _log_action(
                session=session,
                user_id=int(user_id),
                rule_id=int(rule.id),
                trigger_type=trigger_type,
                event_payload=event_payload,
                action_taken=action_taken,
                action_result=action_result,
            )
            matches.append(
                {
                    "rule_id": int(rule.id),
                    "rule_name": str(rule.name or ""),
                    "action_type": str(rule.action_type or ""),
                    "action_taken": action_taken,
                    "result": action_result,
                }
            )
            log_execution(
                user_id=int(user_id),
                action_type=action_type or "automation_action",
                source="automation",
                payload_json={"rule_id": int(rule.id), "trigger_type": trigger_type, "event_payload": event_payload},
                result_json=action_result,
                status="success" if bool(action_result.get("ok", True)) else "failed",
                execution_id=f"automation_{int(rule.id)}",
                reasoning_summary=f"Automation action '{action_taken}' evaluated for rule '{rule.name}'.",
                why_action_taken=f"Rule matched trigger '{trigger_type}' and condition filters.",
                data_influenced_json={"trigger_type": trigger_type, "rule_id": int(rule.id), "condition": rule.condition_json or {}},
            )
            record_outcome(
                user_id=int(user_id),
                organization_id=int(event.get("organization_id") or 0),
                source_type="business",
                source_id=int(rule.id),
                input_data={"trigger_type": trigger_type, "rule_name": rule.name, "action_type": action_type},
                outcome={
                    "success": bool(action_result.get("ok", True)),
                    "action_taken": action_taken,
                    "profit_loss": float(action_result.get("realized_profit") or 0),
                    "note": f"Automation action {action_taken}",
                },
            )
        session.commit()
        update_strategy_profiles(int(user_id))
        return {"ok": True, "matches": matches, "count": len(matches)}


def list_rules(user_id: int) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        rows = (
            session.execute(
                select(AutomationRule)
                .where(AutomationRule.user_id == int(user_id))
                .order_by(AutomationRule.created_at.desc(), AutomationRule.id.desc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(r.id),
                "name": str(r.name or ""),
                "trigger_type": str(r.trigger_type or ""),
                "condition_json": r.condition_json or {},
                "action_type": str(r.action_type or ""),
                "action_config_json": r.action_config_json or {},
                "enabled": bool(r.enabled),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def upsert_rule(
    *,
    user_id: int,
    rule_id: int | None,
    name: str,
    trigger_type: str,
    condition_json: dict[str, Any],
    action_type: str,
    action_config_json: dict[str, Any],
    enabled: bool,
) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        row = None
        if rule_id:
            row = session.execute(
                select(AutomationRule).where(AutomationRule.id == int(rule_id), AutomationRule.user_id == int(user_id))
            ).scalar_one_or_none()
        if row is None:
            row = AutomationRule(user_id=int(user_id))
            session.add(row)
        row.name = str(name or "").strip() or "Automation rule"
        row.trigger_type = str(trigger_type or "").strip() or "new_data"
        row.condition_json = condition_json or {}
        row.action_type = str(action_type or "").strip() or "notify"
        row.action_config_json = action_config_json or {}
        row.enabled = bool(enabled)
        session.commit()
        return {"id": int(row.id)}


def delete_rule(*, user_id: int, rule_id: int) -> bool:
    factory = _session_factory_or_none()
    if factory is None:
        return False
    with factory() as session:
        row = session.execute(
            select(AutomationRule).where(AutomationRule.id == int(rule_id), AutomationRule.user_id == int(user_id))
        ).scalar_one_or_none()
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def list_automation_logs(user_id: int, limit: int = 80) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 200))
    with factory() as session:
        rows = (
            session.execute(
                select(AutomationLog)
                .where(AutomationLog.user_id == int(user_id))
                .order_by(AutomationLog.created_at.desc(), AutomationLog.id.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(r.id),
                "rule_id": int(r.rule_id) if r.rule_id else None,
                "trigger_type": str(r.trigger_type or ""),
                "event_json": r.event_json or {},
                "action_taken": str(r.action_taken or ""),
                "action_result_json": r.action_result_json or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
