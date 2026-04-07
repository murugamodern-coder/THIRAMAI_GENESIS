"""
Statutory calendar + compliance case checks (Phase 5). Not legal advice — India GST-style due dates as templates.
"""

from __future__ import annotations

import calendar
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import ComplianceCase, Notification


# Normalized filing-complete statuses (case-insensitive, spaces → underscores).
FILING_DONE_TOKENS = frozenset({"filing_done", "done", "closed", "filed"})


def _status_is_filing_done(raw: str) -> bool:
    t = (raw or "").strip().lower().replace(" ", "_")
    return t in FILING_DONE_TOKENS or raw.strip().lower() == "filing done"


@dataclass(frozen=True)
class StatutoryRule:
    key: str
    label: str
    day_of_month: int
    category: str  # GST | Legal | Audit


def _default_statutory_rules() -> list[StatutoryRule]:
    """Hard-coded monthly anchors; override count via env or future DB config."""
    raw = (os.getenv("THIRAMAI_STATUTORY_RULES_JSON") or "").strip()
    if raw:
        try:
            import json

            data = json.loads(raw)
            out: list[StatutoryRule] = []
            for row in data if isinstance(data, list) else []:
                if not isinstance(row, dict):
                    continue
                out.append(
                    StatutoryRule(
                        key=str(row.get("key") or "")[:64],
                        label=str(row.get("label") or row.get("key") or "")[:200],
                        day_of_month=int(row.get("day_of_month") or row.get("day") or 1),
                        category=str(row.get("category") or "GST")[:32],
                    )
                )
            return [r for r in out if r.key]
        except Exception:
            pass
    return [
        StatutoryRule("gstr1", "GSTR-1 (monthly)", 11, "GST"),
        StatutoryRule("gstr3b", "GSTR-3B (monthly)", 20, "GST"),
        StatutoryRule("cmp08", "CMP-08 (composition)", 18, "GST"),
    ]


def deadline_for_month(rule: StatutoryRule, year: int, month: int) -> date:
    """Clamp day to last day of month (e.g. February)."""
    last = calendar.monthrange(year, month)[1]
    d = min(max(1, rule.day_of_month), last)
    return date(year, month, d)


def external_ref_for_period(rule_key: str, year: int, month: int) -> str:
    return f"statutory:{rule_key}:{year}-{month:02d}"


def days_until_deadline(today: date, deadline: date) -> int:
    return (deadline - today).days


def filing_done_for_period(
    session: Session,
    *,
    organization_id: int,
    external_ref: str,
) -> bool:
    rows = session.execute(
        select(ComplianceCase).where(
            ComplianceCase.organization_id == int(organization_id),
            ComplianceCase.external_ref == external_ref,
        )
    ).scalars().all()
    return any(_status_is_filing_done(c.status) for c in rows)


def list_upcoming_statutory_context(
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Human-readable rows for AI / dispatcher (current month obligations)."""
    d = today or datetime.now(timezone.utc).date()
    rules = _default_statutory_rules()
    out: list[dict[str, Any]] = []
    for r in rules:
        dl = deadline_for_month(r, d.year, d.month)
        out.append(
            {
                "key": r.key,
                "label": r.label,
                "category": r.category,
                "deadline": dl.isoformat(),
                "days_remaining": days_until_deadline(d, dl),
                "external_ref": external_ref_for_period(r.key, d.year, d.month),
            }
        )
    return out


def ensure_compliance_notifications(
    organization_id: int,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Insert deduped ``notifications`` when within 3 days before (or on) deadline and no filing-done case.

    Also nags if deadline passed and still not marked filed.
    """
    oid = int(organization_id)
    factory: sessionmaker[Session] | None = get_session_factory()  # type: ignore[assignment]
    if factory is None:
        return {"ok": False, "error": "no_database", "inserted": 0}

    d = today or datetime.now(timezone.utc).date()
    rules = _default_statutory_rules()
    inserted = 0

    with factory() as session:
        with session.begin():
            for r in rules:
                dl = deadline_for_month(r, d.year, d.month)
                ref = external_ref_for_period(r.key, d.year, d.month)
                if filing_done_for_period(session, organization_id=oid, external_ref=ref):
                    continue
                du = days_until_deadline(d, dl)
                if du > 3:
                    continue

                if du < 0:
                    severity, kind = "critical", "compliance_overdue"
                    title = f"⚠️ Overdue: {r.label}"
                    body = (
                        f"**{r.label}** was due **{dl.isoformat()}** and is not marked **Filing Done** in compliance cases "
                        f"(`external_ref` `{ref}`)."
                    )
                elif du == 0:
                    severity, kind = "critical", "compliance_due_today"
                    title = f"Due today: {r.label}"
                    body = f"**{r.label}** deadline is **today** ({dl.isoformat()}). Confirm filing or update case status to **Filing Done**."
                else:
                    severity, kind = "warning", "compliance_window"
                    title = f"GST / statutory: {r.label} in {du} day(s)"
                    body = f"**{r.label}** due **{dl.isoformat()}** ({du} day(s)). Record **Filing Done** on the matching case when filed."

                dedupe = f"compliance:{kind}:{r.key}:{d.year}-{d.month:02d}"

                exists = session.execute(
                    select(Notification.id).where(
                        Notification.organization_id == oid,
                        Notification.dedupe_key == dedupe,
                    ).limit(1)
                ).scalar_one_or_none()
                if exists is not None:
                    continue
                session.add(
                    Notification(
                        organization_id=oid,
                        kind=kind,
                        severity=severity,
                        title=title,
                        body=body,
                        reference_type="compliance_case",
                        reference_id=None,
                        payload={"statutory_key": r.key, "external_ref": ref, "deadline": dl.isoformat()},
                        dedupe_key=dedupe,
                    )
                )
                inserted += 1

    return {"ok": True, "organization_id": oid, "inserted": inserted}


def planning_note_text(*, today: date | None = None) -> str:
    """
    Short statutory calendar block for council ``planning_note`` (orchestrator).

    Uses template rules only — no DB required. Org-specific filing state is layered elsewhere.
    """
    lines: list[str] = []
    for row in list_upcoming_statutory_context(today):
        du = int(row["days_remaining"])
        label = row.get("label") or row.get("key") or "obligation"
        dl = row.get("deadline") or ""
        if du < 0:
            lines.append(f"- {label}: overdue (deadline {dl}).")
        elif du == 0:
            lines.append(f"- {label}: **due today** ({dl}).")
        else:
            lines.append(f"- {label}: in {du} day(s) (deadline {dl}).")
    if not lines:
        return "Statutory templates: no rules configured (set THIRAMAI_STATUTORY_RULES_JSON or use defaults)."
    return "Statutory calendar (templates — confirm filing in Compliance OS):\n" + "\n".join(lines[:12])


def summarize_compliance_for_briefing(
    organization_id: int,
    *,
    today: date | None = None,
) -> list[str]:
    """Short lines for daily briefing narrative."""
    oid = int(organization_id)
    factory: sessionmaker[Session] | None = get_session_factory()  # type: ignore[assignment]
    d = today or datetime.now(timezone.utc).date()
    lines: list[str] = []
    if factory is None:
        return ["Compliance calendar: database offline."]
    with factory() as session:
        for row in list_upcoming_statutory_context(d):
            ref = row["external_ref"]
            du = int(row["days_remaining"])
            if filing_done_for_period(session, organization_id=oid, external_ref=ref):
                continue
            if du > 3:
                continue
            label = row["label"]
            if du < 0:
                lines.append(f"{label} is **overdue** (deadline {row['deadline']}).")
            elif du == 0:
                lines.append(f"{label} is **due today**.")
            else:
                lines.append(f"{label} in **{du}** day(s) (deadline {row['deadline']}).")
    return lines
