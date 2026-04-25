"""Autonomous research workspace + overnight execution engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import LearningLog, Opportunity, ResearchProject
from services.research_loop_engine import generate_hypotheses
from services.simulation_engine import choose_best_simulated_path


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _default_workspace() -> dict[str, Any]:
    return {
        "sources": [],
        "notes": [],
        "summaries": [],
        "experiments": [],
        "outputs": [],
    }


def create_research_project(user_id: int, organization_id: int, title: str, domain: str = "general") -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = ResearchProject(
            user_id=int(user_id),
            organization_id=int(organization_id),
            title=str(title or "Untitled research project").strip()[:300],
            domain=str(domain or "general").strip()[:64],
            status="pending",
            folders_json=_default_workspace(),
            sources_json={"items": []},
            notes_json={"items": []},
            summaries_json={"iterations": []},
            experiments_json={"hypotheses": [], "ranked": []},
            outputs_json={},
            updated_at=_now(),
        )
        session.add(row)
        session.commit()
        pid = int(row.id)
    return {"ok": True, "project_id": pid, "status": "pending"}


def list_research_projects(user_id: int, limit: int = 80) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable", "items": []}
    with factory() as session:
        rows = (
            session.execute(
                select(ResearchProject)
                .where(ResearchProject.user_id == int(user_id))
                .order_by(ResearchProject.created_at.desc(), ResearchProject.id.desc())
                .limit(max(1, min(int(limit), 300)))
            )
            .scalars()
            .all()
        )
    items = [
        {
            "id": int(r.id),
            "title": str(r.title or ""),
            "domain": str(r.domain or "general"),
            "status": str(r.status or "pending"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
    return {"ok": True, "items": items}


def get_research_project(user_id: int, project_id: int) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        row = session.get(ResearchProject, int(project_id))
        if row is None or int(row.user_id) != int(user_id):
            return None
        return {
            "id": int(row.id),
            "title": str(row.title or ""),
            "domain": str(row.domain or "general"),
            "status": str(row.status or "pending"),
            "folders": row.folders_json or _default_workspace(),
            "sources": row.sources_json or {"items": []},
            "notes": row.notes_json or {"items": []},
            "summaries": row.summaries_json or {"iterations": []},
            "experiments": row.experiments_json or {"hypotheses": [], "ranked": []},
            "outputs": row.outputs_json or {},
            "last_error": row.last_error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def _subtopics_from_title(title: str, domain: str) -> list[str]:
    base = str(title or "").strip()
    d = str(domain or "general")
    return [
        f"{base} market context in {d}",
        f"{base} strategy alternatives",
        f"{base} execution risks and mitigations",
        f"{base} implementation sequencing",
    ]


def _collect_internal_signals(user_id: int, topic: str) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        learns = (
            session.execute(
                select(LearningLog)
                .where(LearningLog.resolved_by_user_id == int(user_id))
                .order_by(LearningLog.created_at.desc(), LearningLog.id.desc())
                .limit(8)
            )
            .scalars()
            .all()
        )
        opps = (
            session.execute(
                select(Opportunity)
                .where(Opportunity.user_id == int(user_id))
                .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
                .limit(8)
            )
            .scalars()
            .all()
        )
    data: list[dict[str, Any]] = []
    for l in learns:
        data.append(
            {
                "source": "internal_learning_log",
                "topic": topic,
                "signal": str(l.lesson_summary or l.action_type or "historical outcome"),
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
        )
    for o in opps:
        data.append(
            {
                "source": "internal_opportunity",
                "topic": topic,
                "signal": str(o.title or "opportunity"),
                "expected_profit": float(o.expected_profit or 0.0),
                "risk_level": str(o.risk_level or "medium"),
            }
        )
    return data


def _collect_web_stub(topic: str, cycle: int) -> list[dict[str, Any]]:
    # Intentional no-side-effect research stub: creates a web exploration trace without execution side effects.
    return [
        {"source": "web", "topic": topic, "query": f"{topic} recent trends", "cycle": cycle},
        {"source": "web", "topic": topic, "query": f"{topic} benchmark cases", "cycle": cycle},
    ]


def _build_final_output(project: dict[str, Any], ranked_hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    top = ranked_hypotheses[0] if ranked_hypotheses else {}
    return {
        "problem_understanding": {
            "title": project.get("title"),
            "domain": project.get("domain"),
            "scope": "Long-running autonomous research with simulation-validated options.",
        },
        "explored_options": ranked_hypotheses[:5],
        "best_solution": top,
        "risks": [
            "Model confidence drift may reduce forecast quality.",
            "Historical internal signals can bias direction.",
            "Execution assumptions require human validation before action.",
        ],
        "next_actions": [
            "Review best solution feasibility with current budget/constraints.",
            "Approve one pilot experiment with clear success metric.",
            "Run one additional overnight cycle if confidence < threshold.",
        ],
    }


def run_research_project(project_id: int, cycles: int = 3) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    with factory() as session:
        row = session.get(ResearchProject, int(project_id))
        if row is None:
            return {"ok": False, "error": "Project not found"}
        row.status = "running"
        row.last_error = None
        row.updated_at = _now()
        session.add(row)
        session.commit()

        try:
            user_id = int(row.user_id)
            topic_title = str(row.title or "")
            domain = str(row.domain or "general")
            subtopics = _subtopics_from_title(topic_title, domain)
            all_sources = []
            all_notes = []
            iterations = []
            hypothesis_rank = []
            for idx in range(max(1, min(int(cycles), 12))):
                cycle_no = idx + 1
                cycle_sources = []
                for t in subtopics:
                    cycle_sources.extend(_collect_web_stub(t, cycle_no))
                    cycle_sources.extend(_collect_internal_signals(user_id, t))
                all_sources.extend(cycle_sources)
                note = {
                    "cycle": cycle_no,
                    "insight": f"Cycle {cycle_no}: identified {len(cycle_sources)} evidence points across web/internal lanes.",
                    "refinement": "Narrow to higher-feasibility hypotheses in subsequent cycle.",
                }
                all_notes.append(note)
                hypotheses = generate_hypotheses(user_id, domain).get("items") or []
                ranked = []
                for h in hypotheses:
                    sim = choose_best_simulated_path(
                        user_id,
                        {"action": "research_hypothesis", "expected_profit": 1000 + (cycle_no * 100)},
                    )
                    chosen = sim.get("chosen_path") or {}
                    feasibility = round(float(chosen.get("success_probability") or 0.0) * (1.0 - float(chosen.get("estimated_risk") or 0.0)), 4)
                    ranked.append(
                        {
                            "cycle": cycle_no,
                            "title": str(h.get("title") or "hypothesis"),
                            "hypothesis": str(h.get("hypothesis") or ""),
                            "feasibility": feasibility,
                            "simulation": chosen,
                        }
                    )
                ranked.sort(key=lambda x: float(x.get("feasibility") or 0), reverse=True)
                hypothesis_rank.extend(ranked)
                iterations.append(
                    {
                        "cycle": cycle_no,
                        "subtopics": subtopics,
                        "evidence_points": len(cycle_sources),
                        "top_hypothesis": ranked[0] if ranked else None,
                    }
                )

            hypothesis_rank.sort(key=lambda x: float(x.get("feasibility") or 0), reverse=True)
            outputs = _build_final_output(
                {"title": topic_title, "domain": domain},
                hypothesis_rank,
            )
            row.sources_json = {"items": all_sources}
            row.notes_json = {"items": all_notes}
            row.summaries_json = {"iterations": iterations}
            row.experiments_json = {"hypotheses": [h.get("hypothesis") for h in hypothesis_rank], "ranked": hypothesis_rank}
            row.outputs_json = outputs
            row.status = "completed"
            row.updated_at = _now()
            session.add(row)
            session.commit()
            return {"ok": True, "project_id": int(row.id), "status": "completed", "iterations": len(iterations)}
        except Exception as exc:
            row.status = "failed"
            row.last_error = str(exc)
            row.updated_at = _now()
            session.add(row)
            session.commit()
            return {"ok": False, "project_id": int(row.id), "status": "failed", "error": str(exc)}
