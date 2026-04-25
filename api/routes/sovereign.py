"""
Stage 5 — Sovereign control plane: chain-of-thought feed, executive digest, world scan triggers,
channel webhooks, LTM self-tuning brief, static dashboard HTML.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, require_roles
from core.orchestrator import run_brain
from core.sovereign_journal import read_recent_cot, sovereign_stage5_enabled
from services.brain_execute import brain_execute
from services import channels_bridge, empire_governance, infra_self_heal, ltm_self_tune, prompt_self_tune, task_aggregator, world_scanner

ROOT = Path(__file__).resolve().parents[2]

router = APIRouter(prefix="/sovereign", tags=["Sovereign Stage 5"])


@router.get("/status")
async def sovereign_status(_user: CurrentUser = Depends(require_roles("owner", "manager"))) -> JSONResponse:
    return JSONResponse(
        content={
            "stage5_enabled": sovereign_stage5_enabled(),
            "scheduler_env": (os.getenv("THIRAMAI_SOVEREIGN_SCHEDULER") or "").strip(),
            "world_scan_hours": (os.getenv("THIRAMAI_WORLD_SCAN_INTERVAL_HOURS") or "4").strip(),
            "empire_governance": empire_governance.empire_governance_enabled(),
            "exception_only_ux": empire_governance.exception_only_ux_enabled(),
            "self_heal": infra_self_heal.self_heal_enabled(),
        }
    )


@router.get("/cot/recent")
async def cot_recent(
    limit: int = 120,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    lim = max(1, min(500, int(limit)))
    rows = read_recent_cot(limit=lim, organization_id=int(_user.organization_id))
    return JSONResponse(content={"items": rows, "count": len(rows)})


@router.get("/cot/stream")
async def cot_stream(
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> StreamingResponse:
    """Server-Sent Events: new CoT steps (poll journal every ~2s)."""

    async def gen():
        seen_ids: set[str] = set()
        while True:
            rows = read_recent_cot(limit=80, organization_id=int(_user.organization_id))
            for r in rows:
                rid = str(r.get("id") or "")
                if not rid:
                    rid = f"{r.get('ts')}|{r.get('phase')}|{str(r.get('detail') or '')[:48]}"
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                line = json.dumps(r, ensure_ascii=False, default=str)
                yield f"data: {line}\n\n"
            if len(seen_ids) > 3000:
                seen_ids = set(list(seen_ids)[-1500:])
            await asyncio.sleep(2.0)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/executive-summary/latest")
async def executive_summary_latest(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    row = task_aggregator.latest_executive_summary(int(_user.organization_id))
    if row is None:
        return JSONResponse(content={"markdown": None, "detail": "No summary yet — run daily job or POST /sovereign/executive-summary/run"})
    return JSONResponse(content={"markdown": row.get("markdown"), "meta": row.get("meta"), "ts": row.get("ts")})


@router.post("/executive-summary/run")
async def executive_summary_run(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    res = brain_execute(
        "Build daily executive summary",
        int(_user.id),
        int(_user.organization_id),
    )
    return JSONResponse(content={"ok": bool((res.get("result") or {}).get("ok")), "result": res.get("result"), "status": res.get("status")})


@router.get("/world-events/recent")
async def world_events_recent(
    limit: int = 12,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor")),
) -> JSONResponse:
    lim = max(1, min(50, int(limit)))
    rows = world_scanner.recent_world_events(int(_user.organization_id), limit=lim)
    return JSONResponse(content={"items": rows})


@router.post("/world-scan/run")
async def world_scan_run(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = brain_execute(
        "Run world scan for organization",
        int(_user.id),
        int(_user.organization_id),
    )
    return JSONResponse(content={"ok": bool((out.get("result") or {}).get("ok")), "result": out.get("result"), "status": out.get("status")})


@router.get("/ltm/tuning-brief")
async def ltm_tuning_brief(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    text = ltm_self_tune.build_self_coder_memory_brief(organization_id=int(_user.organization_id))
    return JSONResponse(content={"markdown": text})


@router.post("/ltm/benchmark")
async def ltm_benchmark(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    return JSONResponse(content=ltm_self_tune.benchmark_ltm_query_ms(organization_id=int(_user.organization_id)))


class InboundBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    channel: str = Field("dashboard", max_length=32)


@router.post("/inbound/classify")
async def inbound_classify(
    body: InboundBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "worker")),
) -> JSONResponse:
    """Return priority routing without side effects."""
    pri = channels_bridge.classify_priority(body.text)
    return JSONResponse(content={"priority": pri})


@router.post("/inbound/auto-reply")
async def inbound_auto_reply(
    body: InboundBody,
    _user: CurrentUser = Depends(require_roles("owner", "manager", "supervisor", "worker", "staff", "admin")),
) -> JSONResponse:
    """
    JARVIS low-priority path: full brain answer. High-priority messages are escalated (notifications + channels).
    """
    routed = channels_bridge.route_inbound_message(
        organization_id=int(_user.organization_id),
        channel=body.channel.strip() or "api",
        text=body.text.strip(),
        trace_id=None,
    )
    if routed.get("priority") == "high":
        return JSONResponse(content=routed)
    try:
        structured = run_brain(
            body.text.strip(),
            int(_user.organization_id),
            actor_role_name=_user.role_name,
            user_id=int(_user.id),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"priority": "low", "error": str(exc), "action": "brain_failed"},
        )
    intent = structured.action_intent
    intent_payload = intent.model_dump() if hasattr(intent, "model_dump") else {"repr": repr(intent)}
    return JSONResponse(
        content={
            "priority": "low",
            "action": "answered",
            "narrative": structured.narrative,
            "action_intent": intent_payload,
        }
    )


class WebhookInboundBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    channel: str = Field("webhook", max_length=32)


@router.post("/webhooks/inbound")
async def webhooks_inbound(
    body: WebhookInboundBody,
    x_thiramai_secret: str | None = Header(None, alias="X-Thiramai-Secret"),
) -> JSONResponse:
    """Telegram/Zapier-style ingress; requires shared secret + ``THIRAMAI_WEBHOOK_ORG_ID``."""
    if not channels_bridge.verify_webhook_secret(x_thiramai_secret):
        raise HTTPException(status_code=403, detail="invalid secret")
    raw_oid = (os.getenv("THIRAMAI_WEBHOOK_ORG_ID") or "").strip()
    if not raw_oid.isdigit():
        raise HTTPException(status_code=503, detail="THIRAMAI_WEBHOOK_ORG_ID not configured")
    oid = int(raw_oid)
    out = channels_bridge.route_inbound_message(
        organization_id=oid,
        channel=body.channel.strip() or "webhook",
        text=body.text.strip(),
        trace_id=None,
    )
    return JSONResponse(content=out)


@router.get("/empire/pl-governance/latest")
async def empire_pl_latest(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    row = empire_governance.latest_pl_governance(int(_user.organization_id))
    return JSONResponse(content=row or {})


@router.post("/empire/pl-governance/run")
async def empire_pl_run(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = brain_execute(
        "Build PL versus market governance analysis",
        int(_user.id),
        int(_user.organization_id),
    )
    return JSONResponse(content={"ok": bool((out.get("result") or {}).get("ok")), "result": out.get("result"), "status": out.get("status")})


@router.get("/empire/opportunity/latest")
async def empire_opp_latest(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    row = empire_governance.latest_weekly_opportunity(int(_user.organization_id))
    return JSONResponse(content=row or {})


@router.post("/empire/opportunity/run")
async def empire_opp_run(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = brain_execute(
        "Build weekly revenue opportunity analysis",
        int(_user.id),
        int(_user.organization_id),
    )
    return JSONResponse(content={"ok": bool((out.get("result") or {}).get("ok")), "result": out.get("result"), "status": out.get("status")})


@router.get("/empire/prompt-tuning/latest")
async def empire_prompt_latest(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    row = prompt_self_tune.latest_prompt_audit(organization_id=int(_user.organization_id))
    return JSONResponse(content=row or {})


@router.post("/empire/prompt-tuning/run")
async def empire_prompt_run(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = brain_execute(
        "Run prompt self tuning analysis",
        int(_user.id),
        int(_user.organization_id),
    )
    return JSONResponse(content={"ok": bool((out.get("result") or {}).get("ok")), "result": out.get("result"), "status": out.get("status")})


@router.post("/empire/self-heal/run")
async def empire_self_heal_run(
    _user: CurrentUser = Depends(require_roles("owner", "manager")),
) -> JSONResponse:
    out = brain_execute(
        "Run infrastructure self-heal scan",
        int(_user.id),
        int(_user.organization_id),
    )
    return JSONResponse(content={"ok": bool((out.get("result") or {}).get("ok")), "result": out.get("result"), "status": out.get("status")})


@router.get("/dashboard", include_in_schema=False)
async def sovereign_dashboard_page(
    _user: CurrentUser = Depends(require_roles("owner", "admin")),
) -> FileResponse:
    path = ROOT / "static" / "sovereign_dashboard.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="sovereign_dashboard.html missing")
    return FileResponse(path, media_type="text/html; charset=utf-8")
