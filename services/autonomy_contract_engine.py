"""Shared autonomy mode/state contracts for autonomous orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog
from services.feedback_engine import feedback_drift
from services.governance_engine import list_execution_logs

_SOURCE_TYPE = "autonomy_state"
_SOURCE_ID = 1
_DEFAULT_MODE = "recommend"
_ALLOWED_MODES = frozenset({"observe", "recommend", "auto_low_risk", "auto_policy"})


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_mode(mode: str | None) -> str:
    m = str(mode or _DEFAULT_MODE).strip().lower()
    return m if m in _ALLOWED_MODES else _DEFAULT_MODE


def get_autonomy_state(user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {
            "ok": True,
            "mode": _DEFAULT_MODE,
            "approval_required_for_high_impact": True,
            "updated_at": None,
        }
    with factory() as session:
        row = (
            session.execute(
                select(LearningLog)
                .where(
                    LearningLog.user_id == int(user_id),
                    LearningLog.source_type == _SOURCE_TYPE,
                    LearningLog.source_id == _SOURCE_ID,
                )
                .order_by(LearningLog.created_at.desc(), LearningLog.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
    if row is None:
        return {
            "ok": True,
            "mode": _DEFAULT_MODE,
            "approval_required_for_high_impact": True,
            "updated_at": None,
        }
    payload = row.outcome_json or {}
    return {
        "ok": True,
        "mode": _coerce_mode(payload.get("mode")),
        "approval_required_for_high_impact": bool(payload.get("approval_required_for_high_impact", True)),
        "updated_at": row.created_at.isoformat() if row.created_at else None,
        "notes": payload.get("notes") or "",
    }


def set_autonomy_state(
    *,
    user_id: int,
    organization_id: int,
    mode: str,
    approval_required_for_high_impact: bool = True,
    notes: str = "",
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    mode_norm = _coerce_mode(mode)
    with factory() as session:
        row = LearningLog(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type=_SOURCE_TYPE,
            source_id=_SOURCE_ID,
            input_data_json={"requested_mode": str(mode or ""), "requested_at": _now().isoformat()},
            outcome_json={
                "mode": mode_norm,
                "approval_required_for_high_impact": bool(approval_required_for_high_impact),
                "notes": str(notes or "")[:500],
            },
            success=True,
            outcome="success",
            action_type="autonomy_mode_update",
            lesson_summary=f"Autonomy mode set to {mode_norm}",
            context={"mode": mode_norm},
            result={"ok": True},
        )
        session.add(row)
        session.commit()
    return get_autonomy_state(int(user_id))


def _pending_approvals_count(user_id: int) -> int:
    logs = list_execution_logs(int(user_id), limit=200).get("items") or []
    count = 0
    for item in logs:
        status = str(item.get("status") or "").lower()
        if status == "blocked":
            count += 1
    return count


def autonomy_heartbeat(user_id: int) -> dict[str, Any]:
    state = get_autonomy_state(int(user_id))
    drift = feedback_drift(int(user_id))
    return {
        "ok": True,
        "state": state,
        "pending_approvals": _pending_approvals_count(int(user_id)),
        "drift": drift,
    }


def maybe_demote_autonomy_mode(user_id: int, organization_id: int) -> dict[str, Any]:
    state = get_autonomy_state(int(user_id))
    mode = _coerce_mode((state or {}).get("mode"))
    trend = str((feedback_drift(int(user_id)).get("trend") or "stable")).lower()
    if trend != "degrading":
        return {"ok": True, "demoted": False, "mode": mode}
    ladder = ["observe", "recommend", "auto_low_risk", "auto_policy"]
    idx = ladder.index(mode) if mode in ladder else 1
    if idx <= 0:
        return {"ok": True, "demoted": False, "mode": "observe"}
    new_mode = ladder[idx - 1]
    out = set_autonomy_state(
        user_id=int(user_id),
        organization_id=int(organization_id),
        mode=new_mode,
        approval_required_for_high_impact=True,
        notes="Auto-demoted due to degrading prediction drift.",
    )
    return {"ok": True, "demoted": True, "mode": new_mode, "state": out}
