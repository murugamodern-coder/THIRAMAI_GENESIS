"""
Executive OS persistence: daily agenda (markdown) and research vault (Groq Markdown reports).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import DailyPlan, DailyPlanSnapshot, ExecutiveVaultDocument, ResearchCorrection, ResearchVault
from services.research_engine_templates import (
    RESEARCH_CATEGORY_DEEP_FINANCIAL,
    RESEARCH_CATEGORY_FINANCIAL_STOCKS,
    RESEARCH_CATEGORY_INDUSTRIAL_ENERGY,
    RESEARCH_CATEGORY_REAL_ESTATE,
    deep_financial_analysis_skeleton,
    detect_research_business_category,
    financial_stocks_skeleton,
    industrial_energy_skeleton,
    real_estate_skeleton,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXEC_VAULT_DIR = _REPO_ROOT / "vault" / "executive_uploads"
_VAULT_ALLOWED_TYPES = frozenset(
    {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
)
_MAX_VAULT_BYTES = 15 * 1024 * 1024


def _factory():
    return get_session_factory()


def _normalize_checklist(raw: Any) -> list[dict[str, Any]]:
    """Checklist items: ``id``, ``title``, ``done``, optional ``remind_at`` (local ``YYYY-MM-DDTHH:mm`` or ISO)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw[:50]:
        if not isinstance(x, dict):
            continue
        title = str(x.get("title", "")).strip()[:500]
        if not title:
            continue
        iid = str(x.get("id", "") or "").strip()
        if not iid:
            iid = str(uuid.uuid4())
        done = bool(x.get("done"))
        ra = x.get("remind_at")
        remind: str | None = None
        if isinstance(ra, str) and ra.strip():
            remind = ra.strip()[:80]
        out.append({"id": iid, "title": title, "done": done, "remind_at": remind})
    return out


def get_daily_plan_for_user(*, user_id: int, for_date: date) -> dict[str, Any] | None:
    uid = int(user_id)
    factory = _factory()
    if factory is None:
        return None
    with factory() as session:
        row = session.execute(
            select(DailyPlan).where(DailyPlan.user_id == uid, DailyPlan.for_date == for_date).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return _daily_plan_to_dict(row)


def _daily_plan_to_dict(row: DailyPlan) -> dict[str, Any]:
    raw = getattr(row, "checklist_json", None)
    checklist = _normalize_checklist(raw) if raw is not None else []
    return {
        "id": int(row.id),
        "user_id": int(row.user_id),
        "for_date": row.for_date.isoformat(),
        "plan_text": row.plan_text or "",
        "status": row.status or "draft",
        "checklist": checklist,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def upsert_daily_plan(
    *,
    user_id: int,
    for_date: date,
    plan_text: str,
    status: str = "draft",
    checklist: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    uid = int(user_id)
    st = (status or "draft").strip().lower()[:32] or "draft"
    text = (plan_text or "").strip()
    norm_checklist = _normalize_checklist(checklist) if checklist is not None else None
    factory = _factory()
    if factory is None:
        return None
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(DailyPlan).where(DailyPlan.user_id == uid, DailyPlan.for_date == for_date).limit(1)
            ).scalar_one_or_none()
            if row is None:
                row = DailyPlan(
                    user_id=uid,
                    for_date=for_date,
                    plan_text=text,
                    status=st,
                    checklist_json=norm_checklist if norm_checklist is not None else [],
                )
                session.add(row)
            else:
                row.plan_text = text
                row.status = st
                if norm_checklist is not None:
                    row.checklist_json = norm_checklist
            session.flush()
            snap_list: list[Any] = list(row.checklist_json) if row.checklist_json is not None else []
            session.add(
                DailyPlanSnapshot(
                    user_id=uid,
                    for_date=for_date,
                    plan_text=text,
                    checklist_json=snap_list,
                )
            )
            session.flush()
            return _daily_plan_to_dict(row)


def list_daily_plan_snapshots(*, user_id: int, limit: int = 40) -> list[dict[str, Any]]:
    uid = int(user_id)
    lim = max(1, min(int(limit), 200))
    factory = _factory()
    if factory is None:
        return []
    with factory() as session:
        rows = session.execute(
            select(DailyPlanSnapshot)
            .where(DailyPlanSnapshot.user_id == uid)
            .order_by(desc(DailyPlanSnapshot.created_at))
            .limit(lim)
        ).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": int(r.id),
                    "for_date": r.for_date.isoformat(),
                    "plan_text": (r.plan_text or "")[:8000],
                    "checklist": _normalize_checklist(r.checklist_json),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


def list_executive_vault_documents(*, user_id: int, organization_id: int, limit: int = 50) -> list[dict[str, Any]]:
    uid = int(user_id)
    oid = int(organization_id)
    lim = max(1, min(int(limit), 100))
    factory = _factory()
    if factory is None:
        return []
    with factory() as session:
        rows = session.execute(
            select(ExecutiveVaultDocument)
            .where(ExecutiveVaultDocument.user_id == uid, ExecutiveVaultDocument.organization_id == oid)
            .order_by(desc(ExecutiveVaultDocument.created_at))
            .limit(lim)
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "original_filename": r.original_filename,
                "content_type": r.content_type,
                "byte_size": int(r.byte_size),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_executive_vault_download(*, user_id: int, organization_id: int, doc_id: int) -> tuple[Path, str] | None:
    uid = int(user_id)
    oid = int(organization_id)
    factory = _factory()
    if factory is None:
        return None
    with factory() as session:
        row = session.get(ExecutiveVaultDocument, int(doc_id))
        if row is None or int(row.user_id) != uid or int(row.organization_id) != oid:
            return None
        p = Path(row.storage_path)
        if not p.is_file():
            return None
        try:
            p.resolve().relative_to(_EXEC_VAULT_DIR.resolve())
        except ValueError:
            return None
        return p, (row.original_filename or p.name)


def save_executive_vault_upload_sync(
    *,
    user_id: int,
    organization_id: int,
    original_filename: str,
    content_type: str,
    data: bytes,
) -> dict[str, Any] | None:
    uid = int(user_id)
    oid = int(organization_id)
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct not in _VAULT_ALLOWED_TYPES:
        return {"ok": False, "error": f"unsupported type: {ct}"}
    raw = data if isinstance(data, (bytes, bytearray)) else b""
    if len(raw) > _MAX_VAULT_BYTES:
        return {"ok": False, "error": "file too large (max 15MB)"}
    if len(raw) == 0:
        return {"ok": False, "error": "empty file"}
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", (original_filename or "upload").strip())[:180] or "upload"
    key = f"{uuid.uuid4().hex}_{safe_name}"
    user_dir = _EXEC_VAULT_DIR / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / key
    dest.write_bytes(raw)
    factory = _factory()
    if factory is None:
        try:
            dest.unlink(missing_ok=True)  # type: ignore[arg-type]
        except OSError:
            pass
        return None
    with factory() as session:
        with session.begin():
            row = ExecutiveVaultDocument(
                user_id=uid,
                organization_id=oid,
                original_filename=safe_name[:512],
                content_type=ct[:128],
                byte_size=len(raw),
                storage_path=str(dest.resolve()),
            )
            session.add(row)
            session.flush()
            return {
                "ok": True,
                "id": int(row.id),
                "original_filename": row.original_filename,
                "content_type": row.content_type,
                "byte_size": int(row.byte_size),
            }


def execute_jarvis_voice_command_sync(
    *,
    user_id: int,
    organization_id: int,
    phrase: str,
) -> dict[str, Any]:
    """
    Parse short voice commands: meetings → personal reminder + optional executive plan line.
    """
    uid = int(user_id)
    oid = int(organization_id)
    p = (phrase or "").strip()
    if not p:
        return {"ok": False, "error": "empty phrase"}
    low = p.lower()
    low = re.sub(r"^(?:hey\s+)?jarvis[,!\s]+", "", low).strip()

    from services.life_os_service import add_personal_reminder

    now = datetime.now(timezone.utc)
    today = now.date()

    def _meeting_title() -> str:
        m = re.search(
            r"(?:meeting|call|appointment)\s+(?:with|about|for)?\s*(.+?)(?:\s+for\s+tomorrow|\s+tomorrow|$)",
            p,
            re.I,
        )
        if m and m.group(1).strip():
            return m.group(1).strip()[:500]
        m2 = re.search(r"(?:schedule|add|book)\s+(?:a\s+)?(?:meeting|call)\s+(.+)", p, re.I)
        if m2 and m2.group(1).strip():
            t = m2.group(1).strip()
            t = re.sub(r"\s+for\s+tomorrow.*$", "", t, flags=re.I).strip()
            return t[:500] or "Meeting"
        return "Meeting"

    if "tomorrow" in low and ("meeting" in low or "call" in low or "schedule" in low or "appointment" in low):
        title = _meeting_title()
        target = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        target = target.replace(hour=9, minute=0, second=0, microsecond=0)
        ok, msg = add_personal_reminder(user_id=uid, remind_at=target, title=title, body_plain=None, fernet=None)
        if not ok:
            return {"ok": False, "error": msg}
        plan_row = get_daily_plan_for_user(user_id=uid, for_date=today)
        line = f"- [ ] **{title}** (tomorrow 09:00 UTC reminder set)\n"
        prev = (plan_row or {}).get("plan_text") or ""
        new_text = (prev.rstrip() + "\n\n" + line).strip()
        raw_cl = (plan_row or {}).get("checklist") if isinstance(plan_row, dict) else None
        upsert_daily_plan(
            user_id=uid,
            for_date=today,
            plan_text=new_text,
            status=((plan_row or {}).get("status") or "draft") if isinstance(plan_row, dict) else "draft",
            checklist=raw_cl if isinstance(raw_cl, list) else [],
        )
        return {"ok": True, "action": "meeting_tomorrow", "title": title, "remind_at": target.isoformat()}

    if "today" in low and ("meeting" in low or "call" in low):
        title = _meeting_title()
        target = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if target <= now:
            target = now + timedelta(hours=1)
        ok, msg = add_personal_reminder(user_id=uid, remind_at=target, title=title, body_plain=None, fernet=None)
        if not ok:
            return {"ok": False, "error": msg}
        return {"ok": True, "action": "meeting_today", "title": title, "remind_at": target.isoformat()}

    return {"ok": False, "error": "could not parse command; try: Jarvis, add a meeting for tomorrow"}


def _parse_env_float(raw: str | None, default: float) -> float:
    try:
        return float((raw or "").strip())
    except ValueError:
        return default


def _parse_env_int(raw: str | None, default: int) -> int:
    try:
        return int((raw or "").strip())
    except ValueError:
        return default


def _global_truths_block() -> str:
    """
    Tenant "global truths" for solar / DPR-style research. Override via env; used as CAPEX/land anchors.
    Defaults: ₹4.5 Cr/MW, 5 acres/MW.
    """
    capex_inr = _parse_env_int(os.getenv("THIRAMAI_RESEARCH_CAPEX_INR_PER_MW"), 45_000_000)
    acres_per_mw = _parse_env_float(os.getenv("THIRAMAI_RESEARCH_LAND_ACRES_PER_MW"), 5.0)
    capex_cr = capex_inr / 10_000_000.0
    return (
        "**GLOBAL TRUTHS** (mandatory anchors — **override** generic AI or web-default guesses; only ignore if "
        "the user's topic explicitly supplies a conflicting mandated figure):\n\n"
        f"- **Installed CAPEX:** **₹{capex_inr:,} INR per MW** (≈ **₹{capex_cr:.2f} Cr/MW**).\n"
        f"- **Land intensity:** **{acres_per_mw:g} acres per MW** for ground-mount solar planning.\n\n"
        "Apply these in **Technical Specifications**, **15-Year Cash Flow** sizing, and sensitivity narratives. "
        "Repeat them in an assumptions call-out."
    )


def _operator_corrections_block(*, user_id: int | None, organization_id: int | None) -> str:
    """Latest prioritized feedback from ``research_corrections`` (Command Bar, etc.)."""
    if user_id is None or organization_id is None:
        return ""
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0 or oid <= 0:
        return ""
    factory = _factory()
    if factory is None:
        return ""
    with factory() as session:
        rows = session.execute(
            select(ResearchCorrection)
            .where(ResearchCorrection.user_id == uid, ResearchCorrection.organization_id == oid)
            .order_by(desc(ResearchCorrection.priority), desc(ResearchCorrection.created_at))
            .limit(24)
        ).scalars().all()
    if not rows:
        return ""
    bullets: list[str] = []
    for r in rows:
        src = (r.source or "note").strip() or "note"
        body = (r.feedback_text or "").strip().replace("\r\n", "\n")[:4000]
        if not body:
            continue
        bullets.append(f"- **[{src}]** (priority {int(r.priority)})\n  {body}")
    if not bullets:
        return ""
    return (
        "**OPERATOR RESEARCH FEEDBACK** (treat as **high-priority** corrections for this and future reports — "
        "prefer these over generic training priors when not illegal or factually impossible):\n\n"
        + "\n\n".join(bullets)
    )


def save_research_correction_sync(
    *,
    user_id: int,
    organization_id: int,
    feedback_text: str,
    source: str = "command_bar",
    related_research_vault_id: int | None = None,
    priority: int = 10,
) -> dict[str, Any]:
    """Insert a correction row (Command Bar feedback loop)."""
    uid = int(user_id)
    oid = int(organization_id)
    text = (feedback_text or "").strip()[:8000]
    if not text:
        return {"ok": False, "error": "feedback_text required"}
    src = (source or "command_bar").strip()[:64] or "command_bar"
    pr = max(1, min(int(priority), 1_000_000))
    rid = int(related_research_vault_id) if related_research_vault_id is not None else None
    factory = _factory()
    if factory is None:
        return {"ok": False, "error": "database_unavailable"}
    with factory() as session:
        with session.begin():
            row = ResearchCorrection(
                user_id=uid,
                organization_id=oid,
                feedback_text=text,
                source=src,
                related_research_vault_id=rid,
                priority=pr,
            )
            session.add(row)
            session.flush()
            return {"ok": True, "id": int(row.id), "priority": pr}


def generate_research_markdown_sync(
    *,
    topic: str,
    user_id: int | None = None,
    organization_id: int | None = None,
    business_category: str | None = None,
    user_prompt: str | None = None,
) -> str:
    """Call Groq for a Markdown report using the resolved **business category** template."""
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    from groq import Groq

    model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    client = Groq(api_key=key)
    cat = (business_category or "").strip() or detect_research_business_category(topic)
    corrections = _operator_corrections_block(user_id=user_id, organization_id=organization_id)

    if cat == RESEARCH_CATEGORY_INDUSTRIAL_ENERGY:
        skeleton = industrial_energy_skeleton()
        truths = _global_truths_block()
        system_parts = [skeleton, "", truths]
    elif cat == RESEARCH_CATEGORY_FINANCIAL_STOCKS:
        skeleton = financial_stocks_skeleton()
        system_parts = [skeleton]
    elif cat == RESEARCH_CATEGORY_REAL_ESTATE:
        skeleton = real_estate_skeleton()
        system_parts = [skeleton]
    elif cat == RESEARCH_CATEGORY_DEEP_FINANCIAL:
        skeleton = deep_financial_analysis_skeleton()
        system_parts = [skeleton]
    else:
        skeleton = industrial_energy_skeleton()
        truths = _global_truths_block()
        system_parts = [skeleton, "", truths]

    if corrections:
        system_parts.extend(["", corrections])
    system = "\n".join(system_parts)
    body = (user_prompt if user_prompt is not None else topic).strip()[:8000]
    user_msg = f"Research topic / question:\n\n{body}"
    chat = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    raw = (chat.choices[0].message.content or "").strip()
    if not raw:
        raise RuntimeError("empty_model_response")
    return raw


def save_research_vault_row(
    *,
    session: Session,
    user_id: int,
    organization_id: int,
    topic: str,
    report_markdown: str,
    business_category: str | None = None,
    status: str = "auto_generated",
    resolved_symbol: str | None = None,
    price_at_save: Any = None,
    quote_currency: str | None = None,
) -> ResearchVault:
    bc = (business_category or "").strip()[:32] or None
    st = (status or "auto_generated").strip()[:32] or "auto_generated"
    rs = (resolved_symbol or "").strip()[:48] or None
    qc = (quote_currency or "").strip()[:8] or None
    row = ResearchVault(
        user_id=int(user_id),
        organization_id=int(organization_id),
        topic=topic.strip()[:4000],
        report_markdown=report_markdown,
        business_category=bc,
        status=st,
        resolved_symbol=rs,
        price_at_save=price_at_save,
        quote_currency=qc,
    )
    session.add(row)
    session.flush()
    return row


def create_research_entry(
    *,
    user_id: int,
    organization_id: int,
    topic: str,
    report_markdown: str,
    business_category: str | None = None,
    status: str = "auto_generated",
    resolved_symbol: str | None = None,
    price_at_save: Any = None,
    quote_currency: str | None = None,
) -> dict[str, Any] | None:
    factory = _factory()
    if factory is None:
        return None
    with factory() as session:
        with session.begin():
            row = save_research_vault_row(
                session=session,
                user_id=user_id,
                organization_id=organization_id,
                topic=topic,
                report_markdown=report_markdown,
                business_category=business_category,
                status=status,
                resolved_symbol=resolved_symbol,
                price_at_save=price_at_save,
                quote_currency=quote_currency,
            )
            return _research_row_to_dict(row)


def _research_row_to_dict(row: ResearchVault) -> dict[str, Any]:
    px = row.price_at_save
    return {
        "id": int(row.id),
        "user_id": int(row.user_id),
        "organization_id": int(row.organization_id),
        "topic": row.topic,
        "report_markdown": row.report_markdown,
        "business_category": row.business_category,
        "status": getattr(row, "status", None) or "auto_generated",
        "resolved_symbol": getattr(row, "resolved_symbol", None),
        "price_at_save": float(px) if px is not None else None,
        "quote_currency": getattr(row, "quote_currency", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_research_history(*, user_id: int, organization_id: int, limit: int = 30) -> list[dict[str, Any]]:
    uid = int(user_id)
    oid = int(organization_id)
    lim = max(1, min(int(limit), 100))
    factory = _factory()
    if factory is None:
        return []
    with factory() as session:
        rows = session.execute(
            select(ResearchVault)
            .where(ResearchVault.user_id == uid, ResearchVault.organization_id == oid)
            .order_by(desc(ResearchVault.created_at))
            .limit(lim)
        ).scalars().all()
        return [_research_row_to_dict(r) for r in rows]


def get_research_by_id(*, user_id: int, organization_id: int, entry_id: int) -> dict[str, Any] | None:
    factory = _factory()
    if factory is None:
        return None
    with factory() as session:
        row = session.get(ResearchVault, int(entry_id))
        if row is None:
            return None
        if int(row.user_id) != int(user_id) or int(row.organization_id) != int(organization_id):
            return None
        return _research_row_to_dict(row)
