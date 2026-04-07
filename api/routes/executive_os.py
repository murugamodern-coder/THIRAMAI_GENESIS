"""
Executive OS: daily agenda (markdown), research vault (Groq Markdown), inventory snapshot.

Research uses **business-category templates** (Industrial/Energy with global solar truths, Financial/Stocks,
Real Estate). Auto-detect from topic or pass ``category``; corrections from Command Bar still apply.
See ``services.research_engine_templates`` and ``generate_research_markdown_sync``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse

from api.dependencies import CurrentUser, get_current_user, require_roles
from services.analytics_service import (
    compute_financial_control_tower_sync,
    list_low_stock_alerts_sync,
)
from services import audit_service
from services.executive_os_service import (
    create_research_entry,
    execute_jarvis_voice_command_sync,
    generate_research_markdown_sync,
    get_daily_plan_for_user,
    get_executive_vault_download,
    get_research_by_id,
    list_daily_plan_snapshots,
    list_executive_vault_documents,
    list_research_history,
    save_executive_vault_upload_sync,
    upsert_daily_plan,
)
from services.research_autonomy import plan_autonomous_research
from services.research_engine_templates import category_label

router_executive = APIRouter(prefix="/executive", tags=["Executive OS"])
router_research = APIRouter(prefix="/research", tags=["Research Hub"])


def _require_real_user(user: CurrentUser) -> None:
    if user.id <= 0:
        raise HTTPException(status_code=400, detail="Executive OS requires a real user id.")


class DailyPlanUpsertBody(BaseModel):
    for_date: date | None = Field(None, description="Defaults to today (UTC)")
    plan_text: str = Field("", max_length=200_000)
    status: str = Field("draft", max_length=32)
    checklist: list[dict[str, Any]] | None = Field(
        None,
        description="Sub-tasks: id, title, done, optional remind_at (datetime-local or ISO string).",
    )


class ResearchPostBody(BaseModel):
    topic: str = Field(..., min_length=3, max_length=2000)


class JarvisVoiceBody(BaseModel):
    phrase: str = Field(..., min_length=2, max_length=2000)


_EXEC_ROLES = Depends(
    require_roles("superadmin", "owner", "manager", "supervisor", "admin", "staff"),
)


@router_executive.get(
    "/financial-tower",
    summary="Financial Control Tower time-series (revenue, est. opex, solar ROI projection)",
)
async def executive_financial_tower(
    days: int = Query(14, ge=7, le=90),
    _user: CurrentUser = _EXEC_ROLES,
) -> dict[str, Any]:
    _require_real_user(_user)
    return await asyncio.to_thread(
        compute_financial_control_tower_sync,
        int(_user.organization_id),
        days=int(days),
    )


@router_executive.get("/daily-plan/snapshots", summary="Recent planner versions (history)")
async def executive_daily_plan_snapshots(
    limit: int = Query(40, ge=1, le=200),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _require_real_user(_user)
    rows = await asyncio.to_thread(list_daily_plan_snapshots, user_id=int(_user.id), limit=int(limit))
    return {"ok": True, "items": rows, "count": len(rows)}


@router_executive.post("/jarvis-voice", summary="Push-to-talk planner hooks (e.g. meeting tomorrow)")
async def executive_jarvis_voice(
    body: JarvisVoiceBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _require_real_user(_user)
    out = await asyncio.to_thread(
        execute_jarvis_voice_command_sync,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        phrase=body.phrase.strip(),
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "voice_command_failed")
    return out


@router_executive.get("/vault/documents", summary="List uploaded executive vault files")
async def executive_vault_list(
    limit: int = Query(50, ge=1, le=100),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _require_real_user(_user)
    rows = await asyncio.to_thread(
        list_executive_vault_documents,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        limit=int(limit),
    )
    return {"ok": True, "items": rows}


@router_executive.post("/vault/upload", summary="Upload PDF or image to executive vault")
async def executive_vault_upload(
    file: UploadFile = File(...),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _require_real_user(_user)
    raw = await file.read()
    ct = (file.content_type or "application/octet-stream").strip()
    out = await asyncio.to_thread(
        save_executive_vault_upload_sync,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        original_filename=file.filename or "upload",
        content_type=ct,
        data=raw,
    )
    if out is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "upload_failed")
    return {"ok": True, "document": out}


@router_executive.get("/vault/documents/{doc_id}/file", summary="Download vault file (owner only)")
async def executive_vault_download(
    doc_id: int,
    _user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    _require_real_user(_user)
    pair = await asyncio.to_thread(
        get_executive_vault_download,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        doc_id=int(doc_id),
    )
    if pair is None:
        raise HTTPException(status_code=404, detail="not_found")
    path, fname = pair
    return FileResponse(
        path=str(path),
        filename=fname,
        media_type="application/octet-stream",
    )


@router_executive.get("/daily-plan", summary="Get daily agenda markdown for a date")
async def get_daily_plan(
    for_date: date | None = Query(default=None, description="ISO date; default today UTC"),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    _require_real_user(_user)
    d = for_date or datetime.now(timezone.utc).date()
    row = await asyncio.to_thread(get_daily_plan_for_user, user_id=int(_user.id), for_date=d)
    if row is None:
        return {
            "ok": True,
            "for_date": d.isoformat(),
            "plan_text": "",
            "status": "draft",
            "checklist": [],
            "id": None,
        }
    return {"ok": True, **row}


@router_executive.put("/daily-plan", summary="Upsert daily agenda markdown")
async def put_daily_plan(
    body: DailyPlanUpsertBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    _require_real_user(_user)
    d = body.for_date or datetime.now(timezone.utc).date()
    out = await asyncio.to_thread(
        upsert_daily_plan,
        user_id=int(_user.id),
        for_date=d,
        plan_text=body.plan_text,
        status=body.status,
        checklist=body.checklist,
    )
    if out is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    audit_service.log_life_os_mutation(
        correlation_id=None,
        action_name="executive_daily_plan_upsert",
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        resource_type="daily_plans",
        extra={"for_date": d.isoformat(), "status": out.get("status")},
    )
    return {"ok": True, "plan": out}


@router_executive.get(
    "/inventory-critical",
    summary="SKUs below low-stock threshold (tenant-scoped)",
)
async def inventory_critical(
    threshold: int = Query(5, ge=0, le=10_000),
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "admin", "staff")),
) -> dict:
    oid = int(_user.organization_id)
    data = await asyncio.to_thread(list_low_stock_alerts_sync, oid, threshold=int(threshold))
    items = data.get("items") or []
    return {
        "ok": bool(data.get("ok", True)),
        "organization_id": oid,
        "threshold": int(threshold),
        "count": len(items) if isinstance(items, list) else int(data.get("count") or 0),
        "items": items[:100],
    }


@router_research.post("", summary="Run Groq research and save Markdown to vault")
async def research_post(
    body: ResearchPostBody,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    _require_real_user(_user)
    topic = body.topic.strip()
    plan = await asyncio.to_thread(plan_autonomous_research, topic)
    try:
        md = await asyncio.to_thread(
            generate_research_markdown_sync,
            topic=topic,
            user_id=int(_user.id),
            organization_id=int(_user.organization_id),
            business_category=plan.business_category,
            user_prompt=plan.user_message,
        )
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "groq" in msg or "not configured" in msg:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"research_generation_failed: {exc}") from exc

    saved = await asyncio.to_thread(
        create_research_entry,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        topic=topic,
        report_markdown=md,
        business_category=plan.business_category,
        status="auto_generated",
        resolved_symbol=plan.resolved_yahoo_symbol,
        price_at_save=plan.price_at_save,
        quote_currency=plan.quote_currency,
    )
    if saved is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    audit_service.log_life_os_mutation(
        correlation_id=None,
        action_name="research_vault_create",
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        resource_type="research_vault",
        extra={
            "entry_id": saved.get("id"),
            "topic_preview": topic[:120],
            "business_category": plan.business_category,
            "resolved_symbol": plan.resolved_yahoo_symbol,
        },
    )
    return {
        "ok": True,
        "business_category": plan.business_category,
        "business_category_label": category_label(plan.business_category),
        "resolved_symbol": plan.resolved_yahoo_symbol,
        "equity_match_label": plan.equity_match_label,
        "entry": saved,
    }


@router_research.get("/history", summary="List saved research reports for current user + org")
async def research_history(
    limit: int = Query(30, ge=1, le=100),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    _require_real_user(_user)
    rows = await asyncio.to_thread(
        list_research_history,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        limit=int(limit),
    )
    return {"ok": True, "items": rows, "count": len(rows)}


@router_research.get("/{entry_id}", summary="Get one research vault entry")
async def research_get_one(
    entry_id: int,
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    _require_real_user(_user)
    row = await asyncio.to_thread(
        get_research_by_id,
        user_id=int(_user.id),
        organization_id=int(_user.organization_id),
        entry_id=int(entry_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "entry": row}
