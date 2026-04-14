"""
Personal OS — daily snapshot, AI guidance, streak/score, one-click actions, suggestion feedback.

Backward compatible: ``today_sales``, ``low_stock``, ``guidance.focus``, ``guidance.suggestions`` (texts).
New: ``guidance.top_focus``, ``actionable_suggestions``, ``daily_score``, ``streak_days``, ``sales``/``stock`` aliases.
Personal AI Director (additive): ``life_context``, ``priority_tasks``, ``proactive_alerts``, ``life_score``;
guidance may include ``memory_based_suggestions``, ``director_mode``, ``next_best_move``, ``balance_tip``.
``POST /personal/life-event`` records a life-memory row (JWT), optional ``?include_profile=1``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from api.dependencies import CurrentUser, get_current_user, get_current_user_optional
from core.personal_ai_engine import generate_daily_guidance, generate_evening_summary, merge_director_into_guidance
from core.life_memory import detect_patterns_sync, get_user_profile_sync, record_life_event_sync
from core.personal_director import build_personal_director_bundle_sync
from core.personal_memory_engine import learn_user_patterns_sync
from services.personal_engagement_service import (
    compute_daily_score,
    execute_personal_action_sync,
    record_suggestion_feedback_sync,
    touch_streak_sync,
)
from services.personal_jarvis_sync import (
    build_weekly_personal_report_sync,
    compute_yesterday_followups_sync,
    persist_today_jarvis_snapshot_sync,
)
from services.personal_ambient_sync import build_ambient_sync
from services.personal_os_aggregate import build_personal_today_sync
from services.jarvis_memory_engine import fetch_living_memory_brief_sync
from services.personal_quick_intent_sync import parse_quick_phrase

router = APIRouter(prefix="/personal", tags=["Personal OS"])
logger = logging.getLogger(__name__)


def _build_personal_today_payload_sync(
    *,
    user_id: int,
    organization_id: int,
    authenticated: bool,
    low_stock_threshold: int,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    authed = bool(authenticated)

    payload = build_personal_today_sync(
        user_id=uid,
        organization_id=oid,
        low_stock_threshold=low_stock_threshold,
    )
    payload["authenticated"] = authed
    payload["sales"] = payload.get("today_sales")
    payload["stock"] = payload.get("low_stock")

    streak_days = 0
    eng_extra: dict[str, Any] = {}
    if authed and uid > 0:
        st = touch_streak_sync(uid)
        streak_days = int(st.get("streak_days") or 0)
        eng_extra = st.get("extra") or {}

    score_block = (
        compute_daily_score(payload, eng_extra)
        if authed and uid > 0
        else {"daily_score": 0, "daily_score_breakdown": {}}
    )

    payload["streak_days"] = streak_days
    payload["daily_score"] = score_block["daily_score"]
    payload["daily_score_breakdown"] = score_block["daily_score_breakdown"]

    snap = _snapshot_for_engine(payload, authenticated=authed)
    director_bundle = build_personal_director_bundle_sync(
        payload,
        snap,
        engagement_extra=eng_extra if authed and uid > 0 else None,
    )
    memory = learn_user_patterns_sync(uid, oid) if authed and uid > 0 else {}
    followups = compute_yesterday_followups_sync(uid, payload) if authed and uid > 0 else []
    guidance = generate_daily_guidance(
        snap,
        memory=memory if authed and uid > 0 else None,
        followups=followups or None,
    )
    ge = director_bundle.get("guidance_enrichment")
    if isinstance(ge, dict):
        guidance = merge_director_into_guidance(guidance, ge)
    payload["guidance"] = guidance

    payload["life_context"] = director_bundle.get("life_context") or {}
    payload["priority_tasks"] = director_bundle.get("priority_tasks") or []
    payload["proactive_alerts"] = director_bundle.get("proactive_alerts") or []
    payload["life_score"] = director_bundle.get("life_score") or {}
    payload["ambient"] = build_ambient_sync(payload, guidance)
    if authed and uid > 0:
        persist_today_jarvis_snapshot_sync(
            uid,
            guidance.get("actionable_suggestions") or [],
            guidance.get("focus_lock_target"),
        )
        payload["jarvis_memory"] = {
            "preferred_actions": memory.get("preferred_actions"),
            "ignored_actions": memory.get("ignored_actions"),
            "hint": memory.get("preferred_summary"),
            "stats": memory.get("stats"),
            "living": fetch_living_memory_brief_sync(uid),
        }
    else:
        payload["jarvis_memory"] = {}

    return payload


def _snapshot_for_engine(payload: dict[str, Any], *, authenticated: bool) -> dict[str, Any]:
    return {
        "tasks": payload.get("tasks") or [],
        "reminders": payload.get("reminders") or [],
        "low_stock": payload.get("low_stock") or {},
        "today_sales": payload.get("today_sales") or {},
        "authenticated": authenticated,
        "user_id": int(payload.get("user_id") or 0),
        "organization_id": int(payload.get("organization_id") or 0),
        "daily_score": int(payload.get("daily_score") or 0),
        "streak_days": int(payload.get("streak_days") or 0),
        "habits_completed_today": int(payload.get("habits_completed_today") or 0),
        "tasks_completed_today": int(payload.get("tasks_completed_today") or 0),
        "meeting_nudges": payload.get("meeting_nudges") or [],
    }


class PersonalActionBody(BaseModel):
    """One-click execution (e.g. restock). Maps to safe personal-layer handlers."""

    action: str = Field(..., min_length=1, max_length=64)
    item: str | None = Field(None, max_length=512, description="SKU name for restock")
    quantity: float | None = Field(None, gt=0, le=1_000_000, description="Default 10 for restock")
    mission_id: int | None = Field(None, ge=1, description="For complete_task")
    title: str | None = Field(None, max_length=512, description="For add_task / voice intent")
    feedback: str | None = Field(None, max_length=8000, description="For research_feedback action")


class PersonalFeedbackBody(BaseModel):
    suggestion: str = Field(..., min_length=1, max_length=4000)
    helpful: bool = False


class JarvisProactiveFeedbackBody(BaseModel):
    """Learning loop for persisted proactive alerts (Upgrade 2.1)."""

    alert_dedupe_key: str = Field(..., min_length=1, max_length=256)
    alert_type: str = Field("", max_length=64)
    outcome: Literal["acted", "ignored", "dismissed"]
    meta: dict[str, Any] = Field(default_factory=dict)


class JarvisProactiveExecuteBody(BaseModel):
    dedupe_key: str = Field(..., min_length=1, max_length=256)


class JarvisGoalCreateBody(BaseModel):
    """Upgrade 2.2 — persisted Jarvis goal (e.g. profit target)."""

    description: str = Field(..., min_length=1, max_length=8000)
    organization_id: int | None = Field(None, ge=1)
    goal_type: str | None = Field(None, max_length=64)


class QuickIntentBody(BaseModel):
    phrase: str = Field(..., min_length=1, max_length=2000)


class LifeEventBody(BaseModel):
    """Append one row to ``PersonalEngagement.extra["life_memory_events"]``."""

    kind: Literal["goal", "habit", "decision", "reflection", "note"]
    summary: str = Field(..., min_length=1, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("summary")
    @classmethod
    def _summary_stripped_non_empty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("summary must not be empty")
        return s

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(str(v)) > 12_000:
            raise ValueError("payload too large (max ~12k chars serialized)")
        return v


@router.post("/life-event")
async def personal_life_event(
    body: LifeEventBody,
    user: CurrentUser = Depends(get_current_user),
    include_profile: bool = Query(
        False,
        description="If true, include memory_profile and patterns after write.",
    ),
) -> JSONResponse:
    """
    Record a personal life-memory event (authenticated). Stored in ``PersonalEngagement.extra``.
    """
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    uid = int(user.id)
    oid = int(user.organization_id)

    def _run() -> dict[str, Any]:
        result = record_life_event_sync(
            uid,
            body.kind,
            body.summary,
            payload=body.payload,
            organization_id=oid if oid > 0 else None,
        )
        if not result.get("ok"):
            return {"_error": result.get("error") or "record failed"}

        logger.info(
            "personal_life_event_recorded user_id=%s org_id=%s kind=%s summary_len=%s payload_keys=%s",
            uid,
            oid,
            body.kind,
            len(body.summary),
            len(body.payload) if isinstance(body.payload, dict) else 0,
        )

        out: dict[str, Any] = {"status": "ok"}
        if include_profile:
            out["memory_profile"] = get_user_profile_sync(uid, oid)
            out["patterns"] = detect_patterns_sync(uid, oid)
        return out

    payload = await asyncio.to_thread(_run)
    err = payload.pop("_error", None)
    if err:
        raise HTTPException(status_code=400, detail=str(err))
    return JSONResponse(content=payload)


@router.get("/today")
async def personal_today(
    user: Annotated[CurrentUser | None, Depends(get_current_user_optional)],
    low_stock_threshold: int = Query(5, ge=0, le=10_000),
) -> JSONResponse:
    uid = int(user.id) if user is not None else 0
    oid = int(user.organization_id) if user is not None else 0
    authed = user is not None

    def _run() -> dict:
        return _build_personal_today_payload_sync(
            user_id=uid,
            organization_id=oid,
            authenticated=authed,
            low_stock_threshold=low_stock_threshold,
        )

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.get("/summary")
async def personal_summary(
    user: Annotated[CurrentUser | None, Depends(get_current_user_optional)],
    low_stock_threshold: int = Query(5, ge=0, le=10_000),
) -> JSONResponse:
    uid = int(user.id) if user is not None else 0
    oid = int(user.organization_id) if user is not None else 0
    authed = user is not None

    def _run() -> dict:
        payload = build_personal_today_sync(
            user_id=uid,
            organization_id=oid,
            low_stock_threshold=low_stock_threshold,
        )
        low = payload.get("low_stock") or {}
        n_low = int(low.get("count") or 0)
        eng = touch_streak_sync(uid) if authed and uid > 0 else {"streak_days": 0, "extra": {}}
        score_block = compute_daily_score(payload, eng.get("extra") or {}) if authed and uid > 0 else {
            "daily_score": 0,
            "daily_score_breakdown": {},
        }
        payload["streak_days"] = int(eng.get("streak_days") or 0)
        payload["daily_score"] = score_block["daily_score"]
        return {
            "ok": True,
            "as_of_utc": payload.get("as_of_utc"),
            "authenticated": authed,
            "streak_days": payload["streak_days"],
            "daily_score": score_block["daily_score"],
            "evening": generate_evening_summary(_snapshot_for_engine(payload, authenticated=authed)),
            "quick_counts": {
                "tasks_open": len(payload.get("tasks") or []),
                "reminders_upcoming": len(payload.get("reminders") or []),
                "low_stock_skus": n_low,
            },
        }

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.get("/morning-plan")
async def personal_morning_plan(
    user: Annotated[CurrentUser | None, Depends(get_current_user_optional)],
    low_stock_threshold: int = Query(5, ge=0, le=10_000),
) -> JSONResponse:
    uid = int(user.id) if user is not None else 0
    oid = int(user.organization_id) if user is not None else 0
    authed = user is not None

    def _run() -> dict[str, Any]:
        payload = _build_personal_today_payload_sync(
            user_id=uid,
            organization_id=oid,
            authenticated=authed,
            low_stock_threshold=low_stock_threshold,
        )
        tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
        g = payload.get("guidance") if isinstance(payload.get("guidance"), dict) else {}
        return {
            "ok": True,
            "as_of_utc": payload.get("as_of_utc"),
            "authenticated": authed,
            "streak_days": payload.get("streak_days"),
            "daily_score": payload.get("daily_score"),
            "top_tasks": tasks[:3],
            "top_focus": g.get("top_focus") or g.get("focus"),
            "key_business_focus": g.get("top_focus") or g.get("focus"),
            "focus_lock": g.get("focus_lock"),
            "message": g.get("message"),
            "tone": g.get("tone"),
            "time_mode": g.get("time_mode"),
            "encouragement": g.get("encouragement"),
            "alerts": g.get("alerts") or [],
            "followups": g.get("followups") or [],
            "memory_hint": g.get("memory_hint"),
            "actionable_suggestions": (g.get("actionable_suggestions") or [])[:3],
            "jarvis_memory": payload.get("jarvis_memory") or {},
            "ambient": payload.get("ambient") or {},
        }

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.get("/weekly-report")
async def personal_weekly_report(user: CurrentUser = Depends(get_current_user)) -> JSONResponse:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        return build_weekly_personal_report_sync(int(user.id), int(user.organization_id))

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.post("/quick-intent")
async def personal_quick_intent(
    body: QuickIntentBody,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """Map a short phrase (e.g. ``add task buy stock``) to ``/personal/action`` behavior."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    parsed = parse_quick_phrase(body.phrase)
    if not parsed.get("ok"):
        raise HTTPException(status_code=400, detail=parsed.get("error") or "unmapped phrase")

    act = (parsed.get("action") or "").strip().lower()
    if act in ("restock", "inventory_add", "add_stock"):
        allowed = frozenset({"superadmin", "owner", "manager", "supervisor", "admin", "staff"})
        if (user.role_name or "").strip().lower() not in allowed:
            raise HTTPException(status_code=403, detail="Your role cannot add inventory from Personal OS.")

    def _run() -> dict[str, Any]:
        return execute_personal_action_sync(
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            action=str(parsed["action"]),
            item=parsed.get("item"),
            quantity=parsed.get("quantity"),
            mission_id=parsed.get("mission_id"),
            title=parsed.get("title"),
            feedback=parsed.get("feedback"),
        )

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "action failed")
    return JSONResponse(
        content={
            **out,
            "parsed": {
                "action": parsed.get("action"),
                "title": parsed.get("title"),
                "item": parsed.get("item"),
                "feedback": parsed.get("feedback"),
            },
        }
    )


@router.post("/action")
async def personal_action(
    body: PersonalActionBody,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """Execute a personal one-click action (restock, complete task, UI hints)."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    act = (body.action or "").strip().lower()
    if act in ("restock", "inventory_add", "add_stock"):
        allowed = frozenset({"superadmin", "owner", "manager", "supervisor", "admin", "staff"})
        if (user.role_name or "").strip().lower() not in allowed:
            raise HTTPException(status_code=403, detail="Your role cannot add inventory from Personal OS.")

    def _run() -> dict[str, Any]:
        return execute_personal_action_sync(
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            action=body.action,
            item=body.item,
            quantity=body.quantity,
            mission_id=body.mission_id,
            title=body.title,
            feedback=body.feedback,
        )

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "action failed")
    return JSONResponse(content=out)


@router.post("/feedback")
async def personal_feedback(
    body: PersonalFeedbackBody,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """Store suggestion feedback; mirrors to ``learning_logs`` when organization is present (experiences)."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        return record_suggestion_feedback_sync(
            user_id=int(user.id),
            organization_id=int(user.organization_id) if int(user.organization_id) > 0 else None,
            suggestion=body.suggestion,
            helpful=body.helpful,
        )

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "feedback failed")
    return JSONResponse(content=out)


@router.post("/jarvis-proactive/feedback")
async def jarvis_proactive_feedback(
    body: JarvisProactiveFeedbackBody,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """Record acted / ignored / dismissed for a proactive alert (dedupe_key from Today / agentic API)."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_proactive_service import record_proactive_feedback_sync

        return record_proactive_feedback_sync(
            user_id=int(user.id),
            alert_dedupe_key=body.alert_dedupe_key,
            alert_type=body.alert_type,
            outcome=body.outcome,
            meta=body.meta,
        )

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "record failed")
    return JSONResponse(content=out)


@router.get("/jarvis-proactive/agentic-insights")
async def jarvis_proactive_agentic_insights(
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(12, ge=1, le=40),
) -> JSONResponse:
    """Re-scored proactive insights with dependency reasoning and ``action_ready_payload``."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_proactive_action_engine import user_execution_mode_for_user
        from services.jarvis_proactive_engine import JarvisProactiveEngine

        uid = int(user.id)
        insights = JarvisProactiveEngine.build_intelligent_insights_from_recent(uid, limit=limit)
        return {
            "ok": True,
            "execution_mode": user_execution_mode_for_user(uid),
            "insights": [i.to_agentic_output() for i in insights],
        }

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.post("/jarvis-proactive/execute")
async def jarvis_proactive_execute(
    body: JarvisProactiveExecuteBody,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """Run safe auto-actions for a persisted alert when global mode is ``confirm`` or ``auto``."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_proactive_engine import execute_proactive_insight_action_sync

        return execute_proactive_insight_action_sync(user_id=int(user.id), dedupe_key=body.dedupe_key)

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "execute failed")
    return JSONResponse(content=out)


@router.get("/jarvis-agent/captain-brief")
async def jarvis_agent_captain_brief(user: CurrentUser = Depends(get_current_user)) -> JSONResponse:
    """Narrative partner brief + clustered top-3 critical insights."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_autonomous_agent import cluster_top_insights_sync
        from services.jarvis_narrative import build_captain_narrative_sync

        uid = int(user.id)
        nar = build_captain_narrative_sync(user_id=uid)
        cap = cluster_top_insights_sync(user_id=uid, top_n=3)
        return {**nar, "clustered": cap}

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.get("/jarvis-agent/weekly-strategy")
async def jarvis_agent_weekly_strategy(user: CurrentUser = Depends(get_current_user)) -> JSONResponse:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_weekly_strategy import generate_weekly_strategy_sync

        return generate_weekly_strategy_sync(user_id=int(user.id))

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.post("/jarvis-agent/goals")
async def jarvis_agent_create_goal(
    body: JarvisGoalCreateBody,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_goal_engine import create_goal_sync

        return create_goal_sync(
            user_id=int(user.id),
            description=body.description,
            goal_type=body.goal_type,
            organization_id=body.organization_id,
        )

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "create failed")
    return JSONResponse(content=out)


@router.get("/jarvis-agent/goals")
async def jarvis_agent_list_goals(
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_goal_engine import get_active_goals_sync

        return {"ok": True, "goals": get_active_goals_sync(user_id=int(user.id), limit=limit)}

    return JSONResponse(content=await asyncio.to_thread(_run))


@router.post("/jarvis-agent/goals/{goal_id}/subtasks")
async def jarvis_agent_break_subtasks(
    goal_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")

    def _run() -> dict[str, Any]:
        from services.jarvis_goal_engine import break_into_subtasks_sync

        return break_into_subtasks_sync(goal_id=int(goal_id), user_id=int(user.id))

    out = await asyncio.to_thread(_run)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "subtasks failed")
    return JSONResponse(content=out)


@router.post("/jarvis-agent/cycle")
async def jarvis_agent_run_cycle(user: CurrentUser = Depends(get_current_user)) -> JSONResponse:
    """Run one autonomous agent tick (rate-limited; safe actions only)."""
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user id required")
    oid = int(user.organization_id)

    def _run() -> dict[str, Any]:
        from services.jarvis_autonomous_agent import run_agent_cycle_sync
        from services.jarvis_proactive_engine import _org_ids_for_user

        u = int(user.id)
        oids = _org_ids_for_user(u) if oid <= 0 else [oid] + [x for x in _org_ids_for_user(u) if x != oid]
        return run_agent_cycle_sync(user_id=u, organization_ids=oids[:5])

    return JSONResponse(content=await asyncio.to_thread(_run))
