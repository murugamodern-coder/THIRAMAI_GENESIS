"""
Meta-autonomy layer:
- monitor system performance
- detect capability/domain/failure gaps
- generate self-improvement tasks
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ActionExecutionRun, DomainDominionProfile, ExecutionAuditLog, LearningLog
from services.execution_capability_registry import get_execution_capabilities
from services.execution_memory_store import build_system_failure_playbook
from services.feedback_engine import calculate_prediction_accuracy


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def consolidate_stable_knowledge(
    *,
    user_id: int,
    organization_id: int,
    hours: int = 24 * 30,
) -> dict[str, Any]:
    """
    Periodic memory compression into stable knowledge layer (read-only guidance).
    """
    try:
        factory = get_session_factory()
    except Exception:
        return {"ok": False, "error": "database_unavailable"}
    if factory is None:
        return {"ok": False, "error": "database_unavailable"}
    since = _now() - timedelta(hours=max(24, int(hours)))
    with factory() as session:
        logs = (
            session.execute(
                select(LearningLog).where(
                    LearningLog.user_id == int(user_id),
                    LearningLog.organization_id == int(organization_id),
                    LearningLog.created_at >= since,
                )
            )
            .scalars()
            .all()
        )
        by_source: dict[str, dict[str, float]] = {}
        by_domain: dict[str, dict[str, float]] = {}
        for row in logs:
            src = str(row.source_type or "unknown")
            dom = str(
                ((row.input_data_json or {}) if isinstance(row.input_data_json, dict) else {}).get("domain")
                or ((row.context or {}) if isinstance(row.context, dict) else {}).get("domain")
                or "general"
            )
            b1 = by_source.setdefault(src, {"n": 0.0, "wins": 0.0})
            b1["n"] += 1.0
            b1["wins"] += 1.0 if bool(row.success) else 0.0
            b2 = by_domain.setdefault(dom, {"n": 0.0, "wins": 0.0})
            b2["n"] += 1.0
            b2["wins"] += 1.0 if bool(row.success) else 0.0
        stable = {
            "generated_at": _now().isoformat(),
            "window_hours": int(hours),
            "sample_size": len(logs),
            "source_patterns": [
                {
                    "source_type": k,
                    "success_rate": round(v["wins"] / max(1.0, v["n"]), 4),
                    "count": int(v["n"]),
                }
                for k, v in sorted(by_source.items(), key=lambda kv: kv[1]["n"], reverse=True)[:20]
            ],
            "domain_patterns": [
                {
                    "domain": k,
                    "success_rate": round(v["wins"] / max(1.0, v["n"]), 4),
                    "count": int(v["n"]),
                }
                for k, v in sorted(by_domain.items(), key=lambda kv: kv[1]["n"], reverse=True)[:20]
            ],
        }
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is not None:
            meta = dict(row.meta_json or {})
            hist = list(meta.get("stable_knowledge_history") or [])
            hist.append(stable)
            meta["stable_knowledge_history"] = hist[-24:]
            meta["stable_knowledge_layer"] = stable
            row.meta_json = meta
            row.updated_at = _now()
            session.commit()
    return {"ok": True, "stable_knowledge_layer": stable}


def monitor_system_performance(
    *,
    user_id: int,
    organization_id: int,
    hours: int = 24 * 7,
) -> dict[str, Any]:
    """
    Track failure rate, retry patterns, and domain success rates.
    """
    try:
        factory = get_session_factory()
    except Exception:
        return {"ok": False, "error": "database_unavailable"}
    if factory is None:
        return {"ok": False, "error": "database_unavailable"}

    since = _now() - timedelta(hours=max(1, int(hours)))
    with factory() as session:
        audit_rows = (
            session.execute(
                select(ExecutionAuditLog).where(
                    ExecutionAuditLog.user_id == int(user_id),
                    ExecutionAuditLog.created_at >= since,
                )
            )
            .scalars()
            .all()
        )
        run_rows = (
            session.execute(
                select(ActionExecutionRun).where(
                    ActionExecutionRun.user_id == int(user_id),
                    ActionExecutionRun.organization_id == int(organization_id),
                    ActionExecutionRun.created_at >= since,
                )
            )
            .scalars()
            .all()
        )
        learn_rows = (
            session.execute(
                select(LearningLog).where(
                    LearningLog.user_id == int(user_id),
                    LearningLog.organization_id == int(organization_id),
                    LearningLog.created_at >= since,
                )
            )
            .scalars()
            .all()
        )

    total_audit = len(audit_rows)
    failed_audit = sum(1 for r in audit_rows if str(r.status or "").lower() in {"failed", "blocked"})
    failure_rate = (failed_audit / max(1, total_audit)) if total_audit else 0.0

    retry_counts: list[int] = []
    for r in run_rows:
        meta = r.meta_json if isinstance(r.meta_json, dict) else {}
        ar = meta.get("auto_retry") if isinstance(meta.get("auto_retry"), dict) else {}
        retry_counts.append(int(ar.get("count") or 0))
    avg_retry = (sum(retry_counts) / max(1, len(retry_counts))) if retry_counts else 0.0
    high_retry_runs = sum(1 for x in retry_counts if int(x) >= 2)

    by_domain: dict[str, dict[str, float]] = {}
    for row in learn_rows:
        inp = row.input_data_json if isinstance(row.input_data_json, dict) else {}
        ctx = row.context if isinstance(row.context, dict) else {}
        domain = str(inp.get("domain") or ctx.get("domain") or "general")
        b = by_domain.setdefault(domain, {"n": 0.0, "wins": 0.0})
        b["n"] += 1.0
        b["wins"] += 1.0 if bool(row.success) else 0.0
    domain_success_rates = [
        {
            "domain": d,
            "success_rate": round((v["wins"] / max(1.0, v["n"])) * 100.0, 2),
            "sample_size": int(v["n"]),
        }
        for d, v in by_domain.items()
    ]
    domain_success_rates.sort(key=lambda x: float(x.get("success_rate") or 0.0))

    return {
        "ok": True,
        "window_hours": int(hours),
        "failure_rate": round(failure_rate, 4),
        "retry_patterns": {
            "average_retry_count": round(avg_retry, 3),
            "high_retry_runs": int(high_retry_runs),
            "sample_runs": len(retry_counts),
        },
        "domain_success_rates": domain_success_rates[:20],
    }


def detect_meta_autonomy_gaps(
    *,
    user_id: int,
    organization_id: int,
    command_probe: str = "health check workflow automation",
) -> dict[str, Any]:
    perf = monitor_system_performance(user_id=int(user_id), organization_id=int(organization_id))
    caps = get_execution_capabilities(
        user_id=int(user_id),
        organization_id=int(organization_id),
        command=str(command_probe or ""),
    )
    playbook = build_system_failure_playbook(
        user_id=int(user_id),
        organization_id=int(organization_id),
        limit=300,
        min_cluster_count=2,
    )
    weak_domains = [
        x
        for x in list(perf.get("domain_success_rates") or [])
        if _safe_float(x.get("success_rate"), 100.0) < 55.0 and int(x.get("sample_size") or 0) >= 3
    ]
    repeated_failures = [
        x
        for x in list(playbook.get("clusters") or [])
        if int(x.get("count") or 0) >= 3
    ]
    missing_tools: list[dict[str, Any]] = []
    for k, v in (caps.get("capabilities") or {}).items():
        if not isinstance(v, dict):
            continue
        if not bool(v.get("available")):
            missing_tools.append({"capability": str(k), "detail": "connector unavailable"})
    return {
        "ok": True,
        "performance": perf,
        "missing_tools": missing_tools,
        "weak_domains": weak_domains[:10],
        "repeated_failures": repeated_failures[:12],
        "system_failure_playbook": playbook,
    }


def generate_self_improvement_tasks(
    *,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    gaps = detect_meta_autonomy_gaps(user_id=int(user_id), organization_id=int(organization_id))
    tasks: list[dict[str, Any]] = []
    perf = gaps.get("performance") if isinstance(gaps.get("performance"), dict) else {}
    failure_rate = _safe_float(perf.get("failure_rate"), 0.0)
    if failure_rate > 0.30:
        tasks.append(
            {
                "title": "Reduce system failure rate via targeted reliability sprint",
                "why": f"Failure rate is {round(failure_rate*100, 1)}% over recent window.",
                "horizon": "mid_term",
                "priority_0_1": 0.92,
                "task_type": "reliability",
            }
        )
    rp = perf.get("retry_patterns") if isinstance(perf.get("retry_patterns"), dict) else {}
    if _safe_float(rp.get("average_retry_count"), 0.0) >= 1.0:
        tasks.append(
            {
                "title": "Refine retry policies for top repeated failure classes",
                "why": "Retry intensity indicates repeated non-adaptive recovery patterns.",
                "horizon": "short_term",
                "priority_0_1": 0.88,
                "task_type": "retry_optimization",
            }
        )
    tool_specs: list[dict[str, Any]] = []
    for m in list(gaps.get("missing_tools") or [])[:4]:
        cap = str(m.get("capability") or "")
        tool_specs.append(
            {
                "tool_name": f"proposed_{cap}",
                "capability_gap": cap,
                "spec": {
                    "inputs": ["context", "target"],
                    "outputs": ["status", "result", "errors"],
                    "safety_contract": [
                        "no_side_effects_without_explicit_operator_approval",
                        "respect_governor_and_kill_switch",
                        "emit_audit_log_for_all_invocations",
                    ],
                },
                "approval_required": True,
                "execution_mode": "assist_only",
            }
        )
        tasks.append(
            {
                "title": f"Enable missing capability: {m.get('capability')}",
                "why": str(m.get("detail") or "missing execution tool"),
                "horizon": "short_term",
                "priority_0_1": 0.86,
                "task_type": "capability_gap",
            }
        )
    for w in list(gaps.get("weak_domains") or [])[:4]:
        tasks.append(
            {
                "title": f"Improve weak domain strategy: {w.get('domain')}",
                "why": f"Domain success rate {w.get('success_rate')}% with sample {w.get('sample_size')}.",
                "horizon": "long_term",
                "priority_0_1": 0.84,
                "task_type": "domain_weakness",
            }
        )
    for f in list(gaps.get("repeated_failures") or [])[:5]:
        tasks.append(
            {
                "title": f"Harden failure cluster: {f.get('step_kind')} / {f.get('error_class')}",
                "why": f"Repeated failure count {f.get('count')} in domain {f.get('domain')}.",
                "horizon": "short_term",
                "priority_0_1": 0.9,
                "task_type": "failure_cluster",
            }
        )
    tasks.sort(key=lambda x: float(x.get("priority_0_1") or 0.0), reverse=True)
    feedback_loop = {
        "window_hours": int((perf.get("window_hours") or 24 * 7) if isinstance(perf, dict) else 24 * 7),
        "failure_rate": float(perf.get("failure_rate") or 0.0) if isinstance(perf, dict) else 0.0,
        "retry_average": float((perf.get("retry_patterns") or {}).get("average_retry_count") or 0.0)
        if isinstance(perf, dict)
        else 0.0,
        "learning_signal": "tighten" if failure_rate > 0.30 else "stabilize",
    }
    prioritized: list[dict[str, Any]] = []
    for idx, t in enumerate(tasks, start=1):
        row = dict(t)
        base_priority = float(row.get("priority_0_1") or 0.0)
        simulation = {
            "simulated_execution": "no_side_effects",
            "predicted_runtime_hours": round(2.0 + (1.0 - min(1.0, base_priority)) * 10.0, 2),
            "predicted_success_probability": round(max(0.35, min(0.95, 0.5 + (base_priority * 0.45))), 3),
        }
        impact = {
            "predicted_failure_rate_delta": round(-0.12 * base_priority, 4),
            "predicted_domain_success_delta": round(0.10 * base_priority, 4),
            "predicted_cost_units": round(10.0 + (1.0 - base_priority) * 25.0, 2),
            "predicted_value_units": round(25.0 + base_priority * 75.0, 2),
        }
        row["priority_rank"] = int(idx)
        row["assist_only"] = True
        row["reversible"] = True
        row["execution_mode"] = "semi_autonomous" if row.get("task_type") in {"retry_optimization"} else "assist_only"
        row["simulation"] = simulation
        row["impact_prediction"] = impact
        row["feedback_link"] = {
            "expected_metric": "failure_rate" if row.get("task_type") in {"reliability", "failure_cluster"} else "domain_success_rate",
            "review_after_hours": 24 if row.get("task_type") in {"retry_optimization", "failure_cluster"} else 72,
        }
        prioritized.append(row)
    trust = float(calculate_prediction_accuracy(int(user_id), limit=220).get("system_trust_score") or 50.0)
    knowledge = consolidate_stable_knowledge(user_id=int(user_id), organization_id=int(organization_id))
    return {
        "ok": True,
        "generated_at": _now().isoformat(),
        "gaps": gaps,
        "tasks": prioritized[:20],
        "proposed_tools": tool_specs,
        "improvement_prioritization": {
            "method": "priority_then_feedback_signal",
            "assist_only": True,
            "reversible": True,
            "cost_aware": True,
            "value_aware": True,
            "trust_score": trust,
        },
        "learning_feedback_loop": feedback_loop,
        "stable_knowledge": knowledge.get("stable_knowledge_layer") if isinstance(knowledge, dict) else None,
    }


def self_correction_triggers(
    *,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    gaps = detect_meta_autonomy_gaps(user_id=int(user_id), organization_id=int(organization_id))
    perf = gaps.get("performance") if isinstance(gaps.get("performance"), dict) else {}
    fr = _safe_float(perf.get("failure_rate"), 0.0)
    repeated = list(gaps.get("repeated_failures") or [])
    triggers: list[dict[str, Any]] = []
    if fr >= 0.28:
        triggers.append(
            {
                "trigger": "repeated_inefficiency",
                "action": "automatic_strategy_swap",
                "details": "switch to conservative strategy profile for next cycle",
            }
        )
    if repeated:
        triggers.append(
            {
                "trigger": "failure_pattern_detected",
                "action": "failure_pattern_blocking",
                "blocked_clusters": [
                    {
                        "step_kind": str(x.get("step_kind") or ""),
                        "error_class": str(x.get("error_class") or ""),
                        "domain": str(x.get("domain") or ""),
                    }
                    for x in repeated[:8]
                    if isinstance(x, dict)
                ],
            }
        )
    return {
        "ok": True,
        "failure_rate": fr,
        "self_correction_triggers": triggers,
    }
