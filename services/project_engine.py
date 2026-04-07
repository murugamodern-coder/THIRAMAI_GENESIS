"""
Factory Operating System — project lifecycle, manpower, revival cost, AI council hints, Stage-2 failure handling.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import Asset, Notification, ProjectStaffAssignment, ProjectStage, User
from services import billing_guard
from services.membership_service import membership_for_organization
from services.analytics_service import compute_dashboard_summary_sync


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def stage_label(stage: int) -> str:
    if stage == ProjectStage.STAGE_INCOME:
        return "Stage 2 — Income generating (live)"
    if stage == ProjectStage.STAGE_REPAIR:
        return "Stage 3 — Repair / revive (maintenance)"
    if stage == ProjectStage.STAGE_EXPANSION:
        return "Stage 4 — New setup (expansion)"
    return f"Stage {stage}"


def list_projects(organization_id: int, *, session: Session | None = None) -> list[ProjectStage]:
    oid = int(organization_id)
    stmt = (
        select(ProjectStage)
        .where(ProjectStage.organization_id == oid)
        .order_by(ProjectStage.priority.desc(), ProjectStage.id.asc())
    )
    if session is not None:
        return list(session.execute(stmt).scalars().all())
    fac = _factory()
    if fac is None:
        return []
    with fac() as s:
        return list(s.execute(stmt).scalars().all())


def create_project(
    *,
    organization_id: int,
    project_name: str,
    current_stage: int,
    status: str = "active",
    priority: int = 0,
    asset_id: int | None = None,
    revival_cost_inr: Decimal | None = None,
) -> int | None:
    fac = _factory()
    if fac is None:
        return None
    with fac() as session:
        with session.begin():
            if asset_id is not None:
                ast = session.get(Asset, int(asset_id))
                if ast is None or int(ast.organization_id) != int(organization_id):
                    return None
            row = ProjectStage(
                organization_id=int(organization_id),
                project_name=(project_name or "").strip()[:500],
                current_stage=int(current_stage),
                status=(status or "active")[:64],
                priority=int(priority),
                asset_id=int(asset_id) if asset_id is not None else None,
                revival_cost_inr=revival_cost_inr,
            )
            session.add(row)
            session.flush()
            return int(row.id)
    return None


def assign_staff(
    *,
    project_stage_id: int,
    organization_id: int,
    user_id: int,
    role_note: str = "",
) -> tuple[bool, str]:
    fac = _factory()
    if fac is None:
        return False, "database not configured"
    pid = int(project_stage_id)
    uid = int(user_id)
    oid = int(organization_id)
    with fac() as session:
        with session.begin():
            proj = session.get(ProjectStage, pid)
            if proj is None or int(proj.organization_id) != oid:
                return False, "project not found"
            u = session.get(User, uid)
            if u is None:
                return False, "user not found"
            mem = membership_for_organization(session, uid, oid)
            if mem is None:
                return False, "user must have an active membership in this organization"
            existing = session.execute(
                select(ProjectStaffAssignment).where(
                    ProjectStaffAssignment.project_stage_id == pid,
                    ProjectStaffAssignment.user_id == uid,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.role_note = (role_note or "")[:500]
                return True, "updated"
            session.add(
                ProjectStaffAssignment(
                    project_stage_id=pid,
                    user_id=uid,
                    role_note=(role_note or "")[:500],
                )
            )
    return True, "assigned"


def estimate_revival_cost_inr(project: ProjectStage, session: Session) -> Decimal:
    """
    Prefer stored ``revival_cost_inr``; else rough heuristic: 10% of linked asset valuation (if any).
    """
    if project.revival_cost_inr is not None and project.revival_cost_inr > 0:
        return Decimal(project.revival_cost_inr).quantize(Decimal("0.01"))
    if project.asset_id is None:
        return Decimal("0")
    ast = session.get(Asset, int(project.asset_id))
    if ast is None or ast.valuation is None:
        return Decimal("0")
    return (Decimal(ast.valuation) * Decimal("0.10")).quantize(Decimal("0.01"))


def set_revival_cost(project_stage_id: int, cost_inr: Decimal) -> bool:
    fac = _factory()
    if fac is None:
        return False
    with fac() as session:
        with session.begin():
            row = session.get(ProjectStage, int(project_stage_id))
            if row is None:
                return False
            row.revival_cost_inr = Decimal(cost_inr).quantize(Decimal("0.01"))
    return True


def stage2_month_revenue_inr(organization_id: int) -> Decimal:
    """Proxy for 'Stage 2 profit pool': this month's bills revenue (same as dashboard)."""
    oid = int(organization_id)
    summary = compute_dashboard_summary_sync(oid, low_stock_threshold=5)
    if not summary.get("ok"):
        return Decimal("0")
    try:
        raw = (summary.get("revenue_inr") or {}).get("this_month") or "0"
        return Decimal(str(raw).replace(",", "")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def build_factory_os_council_appendix(organization_id: int, *, max_chars: int = 2800) -> str:
    """
    Injected into the council ``planning_note``: autonomous allocation hint Stage 2 → Stage 3.
    """
    oid = int(organization_id)
    if oid <= 0:
        return ""
    fac = _factory()
    if fac is None:
        return ""
    pool = stage2_month_revenue_inr(oid)
    with fac() as session:
        repairs = session.execute(
            select(ProjectStage).where(
                ProjectStage.organization_id == oid,
                ProjectStage.current_stage == ProjectStage.STAGE_REPAIR,
                ProjectStage.status == "active",
            )
        ).scalars().all()
        if not repairs:
            return ""
        lines = [
            "## Factory OS (lifecycle)",
            f"- **Stage 2 profit (proxy — this month bills revenue):** ₹{pool}",
            "- **Stage 3 (repair / revive) projects:**",
        ]
        for p in repairs:
            need = estimate_revival_cost_inr(p, session)
            lines.append(
                f"  - **{p.project_name} (Stage 3)** — revival cost **₹{need}** "
                f"(priority {p.priority}, project id={p.id})"
            )
            if pool >= need > 0:
                lines.append(
                    f"    - **Autonomous decision prompt:** Stage 2 profit is **₹{pool}**; should we allocate "
                    f"**₹{need}** to revive **{p.project_name}** (Stage 3)? Confirm with the Sovereign before moving cash."
                )
            elif need > 0:
                lines.append(
                    f"    - **Gap:** need ₹{need - pool} more vs current month revenue pool for full revival funding."
                )
        staff = session.execute(
            select(ProjectStaffAssignment, ProjectStage, User)
            .join(ProjectStage, ProjectStaffAssignment.project_stage_id == ProjectStage.id)
            .join(User, ProjectStaffAssignment.user_id == User.id)
            .where(ProjectStage.organization_id == oid)
            .limit(40)
        ).all()
        if staff:
            lines.append("- **Manpower (assigned):**")
            for a, pr, u in staff[:15]:
                lines.append(f"  - `{u.email}` → **{pr.project_name}** ({stage_label(pr.current_stage)}) {a.role_note or ''}".strip())
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 30] + "\n_[… clipped …]_"
    return text


def apply_stage2_machine_failure(
    *,
    project_stage_id: int,
    organization_id: int,
) -> tuple[bool, str]:
    """
    Mark Stage-2 project machine failed, pause billing, emit 🔴 emergency notification (deduped).
    """
    oid = int(organization_id)
    pid = int(project_stage_id)
    fac = _factory()
    if fac is None:
        return False, "database not configured"
    with fac() as session:
        with session.begin():
            row = session.get(ProjectStage, pid)
            if row is None or int(row.organization_id) != oid:
                return False, "project not found"
            if row.current_stage != ProjectStage.STAGE_INCOME:
                return False, "machine failure flag applies to Stage 2 (income) projects only"
            row.machine_failed = True
            pname = row.project_name
        billing_guard.set_factory_billing_paused(
            oid,
            True,
            reason=f"Stage 2 machine failure — project «{pname}» (id={pid})",
        )
    _insert_factory_emergency_notification(oid, pid, pname)
    return True, "ok"


def clear_stage2_machine_failure(
    *,
    project_stage_id: int,
    organization_id: int,
    resume_billing: bool = True,
) -> tuple[bool, str]:
    oid = int(organization_id)
    pid = int(project_stage_id)
    fac = _factory()
    if fac is None:
        return False, "database not configured"
    with fac() as session:
        with session.begin():
            row = session.get(ProjectStage, pid)
            if row is None or int(row.organization_id) != oid:
                return False, "project not found"
            row.machine_failed = False
    if resume_billing:
        billing_guard.set_factory_billing_paused(oid, False, reason="")
    return True, "ok"


def _insert_factory_emergency_notification(organization_id: int, project_id: int, project_name: str) -> None:
    fac = _factory()
    if fac is None:
        return
    dedupe = f"factory_s2_machine_down:project:{project_id}"
    body = (
        f"🔴 **Emergency:** Income-stage machine/project **{project_name}** (id **{project_id}**) "
        f"reported **DOWN**. Factory **billing is paused** until cleared. "
        f"Investigate equipment / production line, then POST `/factory/os/projects/{project_id}/clear-failure` "
        f"(or clear billing hold) when safe."
    )
    try:
        with fac() as session:
            with session.begin():
                exists = session.scalar(
                    select(Notification.id).where(
                        Notification.organization_id == int(organization_id),
                        Notification.dedupe_key == dedupe,
                    ).limit(1)
                )
                if exists is not None:
                    return
                session.add(
                    Notification(
                        organization_id=int(organization_id),
                        kind="factory_stage2_machine_down",
                        severity="critical",
                        title=f"Stage 2 machine down: {project_name}",
                        body=body,
                        reference_type="project_stage",
                        reference_id=int(project_id),
                        payload={"project_stage_id": project_id, "project_name": project_name},
                        dedupe_key=dedupe,
                    )
                )
    except Exception:
        pass


def scan_stage2_failures_for_alerts(session: Session, *, org_ids: list[int], today_key: str) -> int:
    """
    For open Stage-2 projects with ``machine_failed``, ensure billing hold + emergency notification.
    Called from ``workers.alert_system`` inside an existing transaction when possible.
    """
    if not org_ids:
        return 0
    stmt = select(ProjectStage).where(
        ProjectStage.organization_id.in_(org_ids),
        ProjectStage.current_stage == ProjectStage.STAGE_INCOME,
        ProjectStage.machine_failed.is_(True),
        ProjectStage.status == "active",
    )
    rows = list(session.execute(stmt).scalars().all())
    created = 0
    for p in rows:
        oid = int(p.organization_id)
        billing_guard.upsert_hold_in_session(
            session,
            oid,
            True,
            reason=f"Stage 2 machine failure — «{p.project_name}» (id={p.id})",
        )
        dedupe = f"factory_s2_machine_down:project:{p.id}"
        body = (
            f"🔴 **Emergency:** Stage 2 project **{p.project_name}** is flagged **machine_failed**. "
            f"Billing hold enforced. (scan {today_key})"
        )
        exists = session.scalar(
            select(Notification.id).where(
                Notification.organization_id == oid,
                Notification.dedupe_key == dedupe,
            ).limit(1)
        )
        if exists is None:
            session.add(
                Notification(
                    organization_id=oid,
                    kind="factory_stage2_machine_down",
                    severity="critical",
                    title=f"Stage 2 machine down: {p.project_name}",
                    body=body,
                    reference_type="project_stage",
                    reference_id=int(p.id),
                    payload={"project_stage_id": int(p.id)},
                    dedupe_key=dedupe,
                )
            )
            created += 1
    return created
