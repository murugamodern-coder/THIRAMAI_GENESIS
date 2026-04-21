"""Persistence for agentic workflow tasks — PostgreSQL ``agent_tasks`` + in-memory fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_engine, get_session_factory
from core.db.models import AgentTask

_log = logging.getLogger("thiramai.agent_tasks_repo")

_MEMORY: dict[str, dict[str, Any]] = {}


def _factory() -> Any:
    return get_session_factory()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_task_row(
    *,
    task_id: str,
    user_id: int,
    organization_id: int,
    os_key: str,
    full_plan_json: dict[str, Any],
    current_step_index: int,
    execution_logs: list[dict[str, Any]],
    correlation_id: str | None = None,
) -> None:
    corr = (correlation_id or "").strip()[:128] or None
    blob = {
        "task_id": task_id,
        "user_id": user_id,
        "organization_id": organization_id,
        "os_key": os_key,
        "full_plan_json": full_plan_json,
        "current_step_index": current_step_index,
        "execution_logs": execution_logs,
        "correlation_id": corr,
        "updated_at": _utc_iso(),
    }
    if get_engine() is None:
        _MEMORY[task_id] = blob
        _log.debug("agent_tasks: memory persist task_id=%s", task_id)
        return

    factory = _factory()
    if factory is None:
        _MEMORY[task_id] = blob
        return

    try:
        with factory() as session:
            existing = session.execute(select(AgentTask).where(AgentTask.task_id == task_id)).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if existing is None:
                session.add(
                    AgentTask(
                        task_id=task_id,
                        user_id=user_id,
                        organization_id=organization_id,
                        os_key=os_key,
                        full_plan_json=dict(full_plan_json),
                        current_step_index=int(current_step_index),
                        execution_logs=list(execution_logs),
                        correlation_id=corr,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                existing.organization_id = int(organization_id)
                existing.os_key = os_key
                existing.full_plan_json = dict(full_plan_json)
                existing.current_step_index = int(current_step_index)
                existing.execution_logs = list(execution_logs)
                existing.correlation_id = corr
                existing.updated_at = now
            session.commit()
    except Exception as exc:
        _log.warning("agent_tasks DB persist failed; using memory fallback: %s", exc)
        _MEMORY[task_id] = blob


def fetch_task_row(task_id: str, *, user_id: int) -> dict[str, Any] | None:
    """Return blob with keys matching persist_task_row or None."""
    eng = get_engine()
    factory = _factory()
    if eng is None or factory is None:
        hit = _MEMORY.get(task_id)
        if hit and int(hit.get("user_id") or -1) == int(user_id):
            return dict(hit)
        return None

    try:
        with factory() as session:
            row = session.execute(
                select(AgentTask).where(AgentTask.task_id == task_id, AgentTask.user_id == int(user_id))
            ).scalar_one_or_none()
            if row is None:
                hit = _MEMORY.get(task_id)
                if hit and int(hit.get("user_id") or -1) == int(user_id):
                    return dict(hit)
                return None
            return {
                "task_id": row.task_id,
                "user_id": int(row.user_id),
                "organization_id": int(row.organization_id),
                "os_key": row.os_key,
                "full_plan_json": dict(row.full_plan_json or {}),
                "current_step_index": int(row.current_step_index or 0),
                "execution_logs": list(row.execution_logs or []),
                "correlation_id": getattr(row, "correlation_id", None),
            }
    except Exception as exc:
        _log.warning("agent_tasks DB load failed; trying memory: %s", exc)
        hit = _MEMORY.get(task_id)
        if hit and int(hit.get("user_id") or -1) == int(user_id):
            return dict(hit)
        return None


def list_tasks_for_user(user_id: int, *, limit: int = 40, os_key: str | None = None) -> list[dict[str, Any]]:
    """Recent agent missions for dashboards (correlation threading + history)."""
    uid = int(user_id)
    lim = max(1, min(int(limit), 100))
    eng = get_engine()
    factory = _factory()
    if eng is None or factory is None:
        rows = sorted(
            (r for r in _MEMORY.values() if int(r.get("user_id") or -1) == uid),
            key=lambda x: str(x.get("updated_at") or ""),
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        for r in rows[:lim]:
            fj = dict(r.get("full_plan_json") or {})
            pay = fj.get("payload") if isinstance(fj, dict) else {}
            title = str((pay or {}).get("title") or "")[:200]
            if os_key and str(r.get("os_key") or "") != os_key:
                continue
            out.append(
                {
                    "task_id": r.get("task_id"),
                    "title": title or None,
                    "os_key": r.get("os_key"),
                    "correlation_id": r.get("correlation_id"),
                    "updated_at": r.get("updated_at"),
                }
            )
        return out

    try:
        from sqlalchemy import desc, select

        if os_key and str(os_key).strip():
            ok = str(os_key).strip().lower()
            stmt = (
                select(AgentTask)
                .where(AgentTask.user_id == uid, AgentTask.os_key == ok)
                .order_by(desc(AgentTask.updated_at))
                .limit(lim)
            )
        else:
            stmt = (
                select(AgentTask)
                .where(AgentTask.user_id == uid)
                .order_by(desc(AgentTask.updated_at))
                .limit(lim)
            )
        with factory() as session:
            hits = session.execute(stmt).scalars().all()
            items: list[dict[str, Any]] = []
            for row in hits:
                fj = dict(row.full_plan_json or {})
                pay = fj.get("payload") if isinstance(fj, dict) else {}
                title = str((pay or {}).get("title") or "")[:200]
                corr = getattr(row, "correlation_id", None)
                fj_corr = fj.get("correlation_id") if isinstance(fj, dict) else None
                items.append(
                    {
                        "task_id": row.task_id,
                        "title": title or None,
                        "os_key": row.os_key,
                        "correlation_id": corr or fj_corr,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                )
            return items
    except Exception as exc:
        _log.warning("list_tasks_for_user failed: %s", exc)
        return []
