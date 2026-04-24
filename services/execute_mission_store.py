"""Mission planning and execution storage for `/execute`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select

from core.database import get_session_factory
from core.db.models import Mission, MissionStep
from services.intent_classifier import classify_intent
from services.modular_execution_services import (
    BuildService,
    BusinessService,
    MoneyService,
    PersonalService,
    ResearchService,
    ServiceExecutionContext,
)
from services.governance_engine import log_execution, validate_action

_INTENT_SERVICES = {
    "personal": PersonalService(),
    "business": BusinessService(),
    "research": ResearchService(),
    "money": MoneyService(),
    "build": BuildService(),
}


@dataclass(frozen=True)
class MissionExecutionContext:
    user_id: int
    organization_id: int
    role_name: str


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def is_complex_command(command: str) -> bool:
    text = str(command or "").strip().lower()
    if not text:
        return False
    complexity_keywords = (
        "start business",
        "build system",
        "research + execute",
        "research and execute",
        "roadmap",
        "plan and execute",
        "multi-step",
        "end-to-end",
    )
    if any(k in text for k in complexity_keywords):
        return True
    connector_count = sum(text.count(token) for token in (" and ", " then ", " after ", " -> ", " + "))
    return connector_count >= 2 or len(text.split()) >= 14


def _mission_title(command: str) -> str:
    compact = " ".join(str(command or "").split()).strip()
    if not compact:
        return "Mission"
    return compact[:120]


def _plan_steps(command: str) -> list[dict[str, Any]]:
    text = str(command or "").strip()
    return [
        {"step_order": 1, "title": "Clarify objective and constraints", "command": f"clarify objective for: {text}"},
        {"step_order": 2, "title": "Research and gather requirements", "command": f"research requirements for: {text}"},
        {"step_order": 3, "title": "Design execution approach", "command": f"design implementation approach for: {text}"},
        {"step_order": 4, "title": "Execute implementation actions", "command": text},
        {"step_order": 5, "title": "Validate outputs and summarize", "command": f"validate and summarize results for: {text}"},
    ]


def create_mission_plan(*, user_id: int, command: str) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    plan = _plan_steps(command)
    with factory() as session:
        mission = Mission(user_id=int(user_id), title=_mission_title(command), status="planned")
        session.add(mission)
        session.flush()
        for row in plan:
            session.add(
                MissionStep(
                    mission_id=int(mission.id),
                    step_order=int(row["step_order"]),
                    title=str(row["title"]),
                    status="pending",
                    result_json={"command": str(row["command"])},
                )
            )
        session.commit()
        return mission_to_payload(mission_id=int(mission.id), user_id=int(user_id))


def mission_to_payload(*, mission_id: int, user_id: int) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        mission = session.execute(
            select(Mission).where(Mission.id == int(mission_id), Mission.user_id == int(user_id))
        ).scalar_one_or_none()
        if mission is None:
            return None
        q: Select[tuple[MissionStep]] = (
            select(MissionStep)
            .where(MissionStep.mission_id == int(mission.id))
            .order_by(MissionStep.step_order.asc(), MissionStep.id.asc())
        )
        steps = session.execute(q).scalars().all()
        return {
            "type": "mission",
            "mission_id": int(mission.id),
            "title": str(mission.title or ""),
            "status": str(mission.status or "planned"),
            "steps": [
                {
                    "id": int(s.id),
                    "step_order": int(s.step_order),
                    "title": str(s.title or ""),
                    "status": str(s.status or "pending"),
                    "result": s.result_json or {},
                }
                for s in steps
            ],
        }


def run_mission_sequentially(*, mission_id: int, ctx: MissionExecutionContext) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        mission = session.execute(
            select(Mission).where(Mission.id == int(mission_id), Mission.user_id == int(ctx.user_id))
        ).scalar_one_or_none()
        if mission is None:
            return {"ok": False, "error": "Mission not found"}
        mission.status = "running"
        session.flush()

        steps = (
            session.execute(
                select(MissionStep)
                .where(MissionStep.mission_id == int(mission.id))
                .order_by(MissionStep.step_order.asc(), MissionStep.id.asc())
            )
            .scalars()
            .all()
        )
        had_failure = False
        for step in steps:
            check = validate_action(
                "mission_execute_step",
                {
                    "user_id": int(ctx.user_id),
                    "domain": "automation",
                    "payload": {"mission_id": int(mission.id), "step_id": int(step.id), "title": step.title},
                },
            )
            if not check.get("allowed"):
                step.status = "failed"
                step.result_json = {"blocked": True, "reason": check.get("reason") or "Governance blocked"}
                had_failure = True
                log_execution(
                    user_id=int(ctx.user_id),
                    action_type="mission_execute_step",
                    source="mission",
                    payload_json={"mission_id": int(mission.id), "step_id": int(step.id), "title": step.title},
                    result_json=step.result_json,
                    status="blocked",
                    execution_id=f"mission_{int(mission.id)}",
                    reasoning_summary="Mission step blocked by governance limits.",
                    why_action_taken="Safety guardrail denied mission step execution.",
                    data_influenced_json={"mission_id": int(mission.id), "step_id": int(step.id), "step_title": step.title},
                )
                break
            step.status = "running"
            session.flush()
            command = str((step.result_json or {}).get("command") or step.title or "").strip()
            intent = classify_intent(command)
            service = _INTENT_SERVICES.get(intent, ResearchService())
            try:
                out = service.execute(
                    command,
                    ServiceExecutionContext(
                        user_id=int(ctx.user_id),
                        organization_id=int(ctx.organization_id),
                        role_name=str(ctx.role_name or ""),
                        conversation_context=[],
                    ),
                )
                ok = str(out.get("status") or "error").lower() == "success"
                step.status = "done" if ok else "failed"
                step.result_json = {"intent": intent, "output": out}
                if not ok:
                    had_failure = True
                    log_execution(
                        user_id=int(ctx.user_id),
                        action_type="mission_execute_step",
                        source="mission",
                        payload_json={"mission_id": int(mission.id), "step_id": int(step.id), "title": step.title},
                        result_json={"intent": intent, "output": out},
                        status="failed",
                        execution_id=f"mission_{int(mission.id)}",
                        reasoning_summary="Service step returned non-success status.",
                        why_action_taken=f"Executed mission step using intent={intent}.",
                        data_influenced_json={"mission_id": int(mission.id), "step_id": int(step.id), "intent": intent},
                    )
                    break
            except Exception as exc:  # pragma: no cover
                step.status = "failed"
                step.result_json = {"intent": intent, "error": str(exc)}
                had_failure = True
                log_execution(
                    user_id=int(ctx.user_id),
                    action_type="mission_execute_step",
                    source="mission",
                    payload_json={"mission_id": int(mission.id), "step_id": int(step.id), "title": step.title},
                    result_json={"intent": intent, "error": str(exc)},
                    status="failed",
                    execution_id=f"mission_{int(mission.id)}",
                    reasoning_summary="Mission step raised exception during execution.",
                    why_action_taken=f"Attempted mission step with intent={intent}; execution crashed.",
                    data_influenced_json={"mission_id": int(mission.id), "step_id": int(step.id), "intent": intent},
                )
                break
            log_execution(
                user_id=int(ctx.user_id),
                action_type="mission_execute_step",
                source="mission",
                payload_json={"mission_id": int(mission.id), "step_id": int(step.id), "title": step.title},
                result_json={"intent": intent, "output": out},
                status="success",
                execution_id=f"mission_{int(mission.id)}",
                reasoning_summary="Mission step executed successfully.",
                why_action_taken=f"Step routed to service intent={intent} based on mission plan.",
                data_influenced_json={"mission_id": int(mission.id), "step_id": int(step.id), "intent": intent},
            )
            session.flush()

        mission.status = "completed"
        session.commit()
        payload = mission_to_payload(mission_id=int(mission.id), user_id=int(ctx.user_id)) or {}
        payload["ok"] = not had_failure
        return payload
