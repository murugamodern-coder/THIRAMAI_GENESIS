"""Persist per-user outcomes so the action layer can bias future runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ExecutionMemoryEntry


def _fingerprint(step_kind: str, payload: dict[str, Any]) -> str:
    stable = json.dumps({"k": step_kind, "p": payload or {}}, sort_keys=True, default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:64]


def record_outcome(
    *,
    user_id: int,
    organization_id: int,
    step_kind: str,
    payload: dict[str, Any],
    success: bool,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        factory = get_session_factory()
    except Exception:
        return
    if factory is None:
        return
    fp = _fingerprint(step_kind, payload)
    with factory() as session:
        session.add(
            ExecutionMemoryEntry(
                user_id=int(user_id),
                organization_id=int(organization_id),
                fingerprint=fp,
                step_kind=str(step_kind or "")[:64],
                success=bool(success),
                summary=str(summary or "")[:512],
                detail_json=detail or {},
            )
        )
        session.commit()


def record_failure_pattern(
    *,
    user_id: int,
    organization_id: int,
    step_kind: str,
    payload: dict[str, Any],
    error_class: str,
    message: str,
    heal_trace: list[dict[str, Any]] | None,
) -> None:
    """Store structured failure for pattern learning (in addition to generic outcome rows)."""
    try:
        factory = get_session_factory()
    except Exception:
        return
    if factory is None:
        return
    fp = f"fail:{_fingerprint(step_kind, {**dict(payload or {}), '_ec': str(error_class)})}"
    with factory() as session:
        session.add(
            ExecutionMemoryEntry(
                user_id=int(user_id),
                organization_id=int(organization_id),
                fingerprint=fp[:128],
                step_kind=f"failure:{(step_kind or '')[:50]}",
                success=False,
                summary=str(message or "")[:512],
                detail_json={
                    "error_class": str(error_class),
                    "step_kind": str(step_kind),
                    "heal_trace": heal_trace or [],
                },
            )
        )
        session.commit()


def recent_failure_hints(
    *, user_id: int, error_class: str | None, limit: int = 5
) -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
    except Exception:
        return []
    if factory is None:
        return []
    lim = max(1, min(int(limit), 30))
    with factory() as session:
        q = (
            select(ExecutionMemoryEntry)
            .where(ExecutionMemoryEntry.user_id == int(user_id), ExecutionMemoryEntry.success.is_(False))
            .order_by(ExecutionMemoryEntry.created_at.desc())
            .limit(lim)
        )
        rows = list(session.execute(q).scalars().all())
        out = []
        for r in rows:
            d = r.detail_json or {}
            if error_class and str(d.get("error_class") or "") != str(error_class):
                continue
            out.append(
                {
                    "step_kind": d.get("step_kind"),
                    "error_class": d.get("error_class"),
                    "summary": str(r.summary or ""),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


def recent_hints(*, user_id: int, step_kind: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
    except Exception:
        return []
    if factory is None:
        return []
    lim = max(1, min(int(limit), 50))
    with factory() as session:
        rows = (
            session.execute(
                select(ExecutionMemoryEntry)
                .where(
                    ExecutionMemoryEntry.user_id == int(user_id),
                    ExecutionMemoryEntry.step_kind == str(step_kind),
                )
                .order_by(ExecutionMemoryEntry.created_at.desc(), ExecutionMemoryEntry.id.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
        return [
            {
                "success": bool(r.success),
                "summary": str(r.summary or ""),
                "detail_json": r.detail_json or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def _infer_domain(step_kind: str) -> str:
    sk = str(step_kind or "").lower()
    if sk.startswith("browser_"):
        return "browser"
    if sk.startswith("plugin_api") or "api" in sk:
        return "api"
    if sk.startswith("plugin_"):
        return "plugin"
    if sk.startswith("internal_"):
        return "internal"
    return "general"


def _strategy_for_cluster(*, error_class: str, step_kind: str, domain: str) -> dict[str, Any]:
    ec = str(error_class or "").lower()
    sk = str(step_kind or "").lower()
    dm = str(domain or "").lower()
    if ("selector" in ec or "element" in ec or "not_found" in ec or "timeout" in ec) and dm == "browser":
        return {
            "strategy_type": "selector_fallback",
            "mutations": {
                "_try_all_selectors": True,
                "__heal_reload_first": True,
                "__heal_increase_timeout": 60000,
            },
            "reason": "Selector-like/browser failure cluster: broaden selector strategy + reload/timeout.",
        }
    if ("api" in ec or "http" in ec or "connection" in ec or "timeout" in ec) and (dm == "api" or sk.startswith("plugin_api")):
        return {
            "strategy_type": "api_fallback_endpoint",
            "mutations": {
                "use_fallback_endpoint": True,
                "fallback_mode": "next_endpoint",
                "retry_with_get_on_fail": True,
            },
            "reason": "API failure cluster: switch endpoint strategy.",
        }
    if "validation" in ec or "schema" in ec or "payload" in ec or "bad_request" in ec:
        return {
            "strategy_type": "payload_adjustment",
            "mutations": {
                "skip_strict_validation": True,
                "__auto_adjust_payload": True,
            },
            "reason": "Validation/payload failure cluster: adapt payload before retry.",
        }
    return {
        "strategy_type": "generic_hardened_retry",
        "mutations": {"__heal_increase_timeout": 45000},
        "reason": "No specialized cluster strategy matched.",
    }


def build_system_failure_playbook(
    *,
    user_id: int,
    organization_id: int,
    limit: int = 240,
    min_cluster_count: int = 2,
) -> dict[str, Any]:
    """
    Cluster failures by (error_class, step_kind, domain) and produce retry strategies.
    """
    try:
        factory = get_session_factory()
    except Exception:
        return {"ok": False, "error": "database_unavailable"}
    if factory is None:
        return {"ok": False, "error": "database_unavailable"}
    lim = max(10, min(int(limit), 1000))
    clusters: dict[str, dict[str, Any]] = {}
    with factory() as session:
        rows = (
            session.execute(
                select(ExecutionMemoryEntry)
                .where(
                    ExecutionMemoryEntry.user_id == int(user_id),
                    ExecutionMemoryEntry.organization_id == int(organization_id),
                    ExecutionMemoryEntry.success.is_(False),
                )
                .order_by(ExecutionMemoryEntry.created_at.desc(), ExecutionMemoryEntry.id.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
    for r in rows:
        d = r.detail_json if isinstance(r.detail_json, dict) else {}
        step_kind = str(d.get("step_kind") or r.step_kind or "").replace("failure:", "")[:64]
        error_class = str(d.get("error_class") or "unknown")[:64]
        domain = _infer_domain(step_kind)
        key = f"{error_class}|{step_kind}|{domain}"
        c = clusters.setdefault(
            key,
            {
                "error_class": error_class,
                "step_kind": step_kind,
                "domain": domain,
                "count": 0,
                "examples": [],
            },
        )
        c["count"] = int(c.get("count") or 0) + 1
        if len(c["examples"]) < 3:
            c["examples"].append(str(r.summary or "")[:220])
    cluster_rows = sorted(clusters.values(), key=lambda x: int(x.get("count") or 0), reverse=True)
    strategies: list[dict[str, Any]] = []
    for c in cluster_rows:
        if int(c.get("count") or 0) < int(min_cluster_count):
            continue
        s = _strategy_for_cluster(
            error_class=str(c.get("error_class") or ""),
            step_kind=str(c.get("step_kind") or ""),
            domain=str(c.get("domain") or ""),
        )
        strategies.append(
            {
                "cluster": {
                    "error_class": c.get("error_class"),
                    "step_kind": c.get("step_kind"),
                    "domain": c.get("domain"),
                    "count": c.get("count"),
                    "examples": c.get("examples") or [],
                },
                "strategy": s,
            }
        )
    return {
        "ok": True,
        "total_failures_scanned": len(rows),
        "clusters": cluster_rows[:60],
        "strategies": strategies[:40],
    }
