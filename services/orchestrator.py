"""
Agentic task orchestrator — Groq JSON plans, human approval gates, step execution.

State is persisted in PostgreSQL table ``agent_tasks`` (see ``services.agent_tasks_repo``);
in-memory fallback when DB is unavailable.

Trading OS: deep execution via ``agent_stock_bridge`` (stock_assistant service path) and
``options_chain_placeholder`` for Nifty / Bank Nifty option chain (replace with broker API).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.agent_stock_bridge import is_options_trade_context
from services.agent_tasks_repo import fetch_task_row, persist_task_row
from services.security.vault_service import (
    mask_for_log,
    resolve_canonical_key,
    sentiment_overlay_active,
    set_sentiment_disabled_until_end_of_day_ist,
    set_user_runtime_kv,
    smart_sizing_active,
)

_log = logging.getLogger("thiramai.services.orchestrator")

_lock = threading.Lock()

_KEYS_PROBE = frozenset(
    {
        "FYERS_CLIENT_ID",
        "FYERS_SECRET_KEY",
        "FYERS_ACCESS_TOKEN",
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "KITE_ACCESS_TOKEN",
        "THIRAMAI_BROKER_PROVIDER",
    }
)


def _plan_model_id() -> str:
    default = "deepseek-r1-distill-llama-70b"
    return (os.getenv("THIRAMAI_AGENT_PLAN_MODEL") or os.getenv("GROQ_AGENT_PLAN_MODEL") or default).strip()


class PlanStepModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step: int = Field(..., ge=1)
    action: str = Field(..., description="search | trade | code | reason")
    description: str = ""
    status: str = "pending_approval"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action", mode="before")
    @classmethod
    def norm_action(cls, v: object) -> str:
        s = str(v or "").strip().lower()
        aliases = {
            "analyze": "trade",
            "buy": "trade",
            "sell": "trade",
            "portfolio": "trade",
            "configure": "configure_system",
            "config": "configure_system",
            "set_env": "configure_system",
            "setup": "configure_system",
            "broker_test": "test_broker_connection",
            "test_broker": "test_broker_connection",
            "verify_broker": "test_broker_connection",
        }
        return aliases.get(s, s)


class AgentPlanPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = ""
    title: str = ""
    steps: list[PlanStepModel] = Field(default_factory=list)

    def normalize_statuses(self) -> None:
        for i, s in enumerate(self.steps):
            if i == 0:
                s.status = "pending_approval"
            else:
                s.status = "queued"


class AgentPlanRuntime(BaseModel):
    """Plan + correlation + runtime logs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    payload: AgentPlanPayload
    user_id: int
    organization_id: int
    original_command: str
    os_key: str = "stock"
    correlation_id: str | None = None
    execution_logs: list[dict[str, Any]] = Field(default_factory=list)
    execution_mode: str = Field(
        "paper",
        description="paper = internal portfolio; live = broker SDK (falls back if keys missing)",
    )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_current_step_index(steps: list[PlanStepModel]) -> int:
    for i, s in enumerate(steps):
        if s.status == "pending_approval":
            return i
    return len(steps)


def _append_log(rt: AgentPlanRuntime, message: str) -> None:
    rt.execution_logs.append({"ts": _utc_iso(), "message": message[:500]})
    if len(rt.execution_logs) > 250:
        rt.execution_logs[:] = rt.execution_logs[-250:]


def _dry_run_force_qty_enabled() -> bool:
    return (os.getenv("THIRAMAI_DRY_RUN_FORCE_QTY") or "").strip().lower() in ("1", "true", "yes", "on")


def _log_broker_order_id_if_present(rt: AgentPlanRuntime, execution: dict[str, Any] | None) -> None:
    if not isinstance(execution, dict):
        return
    oid = execution.get("order_id") or execution.get("id")
    if oid:
        _append_log(rt, f"Broker order_id={oid}")


def _runtime_to_plan_json(rt: AgentPlanRuntime) -> dict[str, Any]:
    return {
        "version": 1,
        "payload": rt.payload.model_dump(mode="json"),
        "original_command": rt.original_command,
        "correlation_id": rt.correlation_id,
        "execution_mode": rt.execution_mode,
    }


def _persist_runtime(rt: AgentPlanRuntime) -> None:
    cursor = _compute_current_step_index(rt.payload.steps)
    persist_task_row(
        task_id=rt.payload.task_id,
        user_id=rt.user_id,
        organization_id=rt.organization_id,
        os_key=rt.os_key,
        full_plan_json=_runtime_to_plan_json(rt),
        current_step_index=cursor,
        execution_logs=list(rt.execution_logs),
        correlation_id=rt.correlation_id,
    )


def _load_runtime_from_row(row: dict[str, Any]) -> AgentPlanRuntime | None:
    try:
        fj = row.get("full_plan_json") or {}
        payload_data = fj.get("payload") if isinstance(fj, dict) else None
        if not payload_data:
            return None
        payload = AgentPlanPayload.model_validate(payload_data)
        logs = row.get("execution_logs") if isinstance(row.get("execution_logs"), list) else []
        mode = str(fj.get("execution_mode") or row.get("execution_mode") or "paper").strip().lower()
        if mode not in ("paper", "live"):
            mode = "paper"
        corr = row.get("correlation_id") if isinstance(row.get("correlation_id"), str) else None
        if not corr and isinstance(fj, dict):
            corr = fj.get("correlation_id") if isinstance(fj.get("correlation_id"), str) else None
        return AgentPlanRuntime(
            payload=payload,
            user_id=int(row["user_id"]),
            organization_id=int(row["organization_id"]),
            original_command=str(fj.get("original_command") or ""),
            os_key=str(row.get("os_key") or "stock"),
            correlation_id=corr,
            execution_logs=[x for x in logs if isinstance(x, dict)],
            execution_mode=mode,
        )
    except Exception as exc:
        _log.warning("hydrate runtime failed: %s", exc)
        return None


def _groq_plan_json(user_command: str, *, os_key: str) -> dict[str, Any] | None:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        _log.warning("agent plan: GROQ_API_KEY missing")
        return None
    system = (
        "You are Jarvis, the planning engine for THIRAMAI. Decompose the user's command into "
        "executable steps for approval. Respond with a single JSON object only.\n\n"
        "Schema:\n"
        '{ "task_id": "<uuid or leave empty>", "title": "<short title>", '
        '"steps": [ { "step": 1, "action": "search|trade|code|reason", '
        '"description": "<clear instruction>", "status": "pending_approval", '
        '"params": { } } ] }\n\n'
        "Rules:\n"
        '- action "search": params include "query".\n'
        '- action "trade": Equity — params.symbol, optional params.side "buy" or "sell" to submit an order on approval '
        '(uses risk-based quantity). optional depth quote|signal|full. '
        'Options — params.instrument "options", params.chain "nifty" or "banknifty", or NIFTY/BANKNIFTY.\n'
        '- action "configure_system": persist one allowed runtime key — params MUST include '
        '"env_key" (e.g. FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_ACCESS_TOKEN, '
        'KITE_API_KEY, THIRAMAI_TRADE_RISK_PERCENT) AND "value" (the secret or number). '
        'For onboarding toggles use params.intent one of '
        '"disable_sentiment_today"|"enable_sentiment_overlay"|"disable_smart_sizing"|"enable_smart_sizing" '
        '(omit env_key/value when using intent).\n'
        '- action "test_broker_connection": verify live broker SDK after configuration — params optional '
        '(execution_hint "live").\n'
        '- action "code": params.instruction optional.\n'
        '- action "reason": params.question optional.\n'
        '- After storing broker credentials (Fyers/Zerodha keys), ALWAYS add a following step '
        'test_broker_connection unless the user explicitly refuses.\n'
        "- Keep 2–8 ordered steps unless trivial.\n"
        f"- Primary OS context: {os_key!r}.\n"
    )
    if os_key.strip().lower() == "research":
        system += (
            "\nResearch OS emphasis:\n"
            '- Start with action "search" (params.query = focused web/news query).\n'
            '- Follow with action "reason" that instructs summarizing Tavily snippets into an executive briefing or formal report '
            '(params.question optional).\n'
            '- Use action "reason" again if you need polish or citations — keep total steps ≤ 8.\n'
        )
    user_block = f"User command:\n{user_command[:12000]}"
    model = _plan_model_id()
    try:
        from groq import Groq

        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_block},
            ],
            temperature=0.2,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        text = (chat.choices[0].message.content or "").strip()
        return json.loads(text)
    except Exception as exc:
        _log.warning("agent plan groq failed model=%s err=%s", model, exc)
        try:
            from groq import Groq

            fallback = (os.getenv("THIRAMAI_AGENT_PLAN_MODEL_FALLBACK") or "llama-3.3-70b-versatile").strip()
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model=fallback,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_block},
                ],
                temperature=0.2,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            text = (chat.choices[0].message.content or "").strip()
            return json.loads(text)
        except Exception as exc2:
            _log.warning("agent plan fallback failed: %s", exc2)
            return None


def _maybe_configure_heuristic(command: str) -> AgentPlanPayload | None:
    """Fast path for onboarding / credential phrases without Groq."""
    tid = str(uuid.uuid4())
    cmd = command.strip()
    low = cmd.lower()

    if ("disable" in low or "turn off" in low) and "sentiment" in low:
        return AgentPlanPayload(
            task_id=tid,
            title="Sentiment overlay off (today)",
            steps=[
                PlanStepModel(
                    step=1,
                    action="configure_system",
                    description=cmd[:480],
                    status="pending_approval",
                    params={"intent": "disable_sentiment_today"},
                ),
            ],
        )

    if ("enable" in low or "turn on" in low) and "sentiment" in low:
        return AgentPlanPayload(
            task_id=tid,
            title="Enable sentiment overlay",
            steps=[
                PlanStepModel(
                    step=1,
                    action="configure_system",
                    description=cmd[:480],
                    status="pending_approval",
                    params={"intent": "enable_sentiment_overlay"},
                ),
            ],
        )

    if ("disable" in low or "turn off" in low) and "smart" in low and "siz" in low:
        return AgentPlanPayload(
            task_id=tid,
            title="Disable smart sizing",
            steps=[
                PlanStepModel(
                    step=1,
                    action="configure_system",
                    description=cmd[:480],
                    status="pending_approval",
                    params={"intent": "disable_smart_sizing"},
                ),
            ],
        )

    if ("enable" in low or "turn on" in low) and "smart" in low and "siz" in low:
        return AgentPlanPayload(
            task_id=tid,
            title="Enable smart sizing",
            steps=[
                PlanStepModel(
                    step=1,
                    action="configure_system",
                    description=cmd[:480],
                    status="pending_approval",
                    params={"intent": "enable_smart_sizing"},
                ),
            ],
        )

    m = re.match(r"(?is)^(set|put)\s+(?:my\s+)?(?:the\s+)?(.+?)\s+(?:to|as)\s+(.+)$", cmd)
    if not m:
        return None
    phrase = m.group(2).strip().lower()
    raw_val = m.group(3).strip().strip('"').strip("'")

    key_candidates: list[tuple[str, str]] = [
        (r"fyers\s+client\s+id", "FYERS_CLIENT_ID"),
        (r"fyers\s+(?:api\s+)?secret", "FYERS_SECRET_KEY"),
        (r"fyers\s+access\s+token", "FYERS_ACCESS_TOKEN"),
        (r"kite\s+api\s+key|zerodha\s+api\s+key", "KITE_API_KEY"),
        (r"kite\s+api\s+secret|zerodha\s+api\s+secret", "KITE_API_SECRET"),
        (r"kite\s+access\s+token|zerodha\s+access\s+token", "KITE_ACCESS_TOKEN"),
        (r"(?:trade\s+)?risk\s+(?:percent|pct|%?)", "THIRAMAI_TRADE_RISK_PERCENT"),
        (r"trading\s+capital", "THIRAMAI_TRADING_CAPITAL_INR"),
        (r"broker\s+provider", "THIRAMAI_BROKER_PROVIDER"),
    ]
    matched: str | None = None
    for pat, ek in key_candidates:
        if re.search(pat, phrase):
            matched = ek
            break
    if matched is None:
        candidate = phrase.upper().replace(" ", "_")
        matched = resolve_canonical_key(candidate)

    if not matched:
        return None

    if matched == "THIRAMAI_BROKER_PROVIDER":
        v = raw_val.strip().lower()
        if v in ("zerodha", "kite"):
            raw_val = "zerodha"
        elif v in ("fyers",):
            raw_val = "fyers"

    steps: list[PlanStepModel] = [
        PlanStepModel(
            step=1,
            action="configure_system",
            description=f"Persist {matched}",
            status="pending_approval",
            params={"env_key": matched, "value": raw_val},
        ),
    ]
    title = f"Configure {matched}"
    if matched in _KEYS_PROBE:
        steps.append(
            PlanStepModel(
                step=2,
                action="test_broker_connection",
                description="Verify broker connectivity",
                status="queued",
                params={"execution_hint": "live"},
            ),
        )
        title = "Broker setup + validation"
    return AgentPlanPayload(task_id=tid, title=title, steps=steps)


def _fallback_plan(command: str) -> AgentPlanPayload:
    tid = str(uuid.uuid4())
    return AgentPlanPayload(
        task_id=tid,
        title="Manual review",
        steps=[
            PlanStepModel(
                step=1,
                action="reason",
                description=f"Review and answer: {command[:500]}",
                status="pending_approval",
                params={"question": command[:2000]},
            )
        ],
    )


def create_plan_from_command(
    command: str,
    *,
    user_id: int,
    organization_id: int,
    os_key: str = "stock",
    correlation_id: str | None = None,
    execution_mode: str = "paper",
) -> dict[str, Any]:
    heur = _maybe_configure_heuristic(command)
    if heur is not None:
        payload = heur
    else:
        raw = _groq_plan_json(command, os_key=os_key)
        if raw and isinstance(raw, dict) and raw.get("steps"):
            try:
                tid = str(raw.get("task_id") or "").strip() or str(uuid.uuid4())
                raw["task_id"] = tid
                payload = AgentPlanPayload.model_validate(raw)
            except Exception as exc:
                _log.warning("agent plan validate failed: %s", exc)
                payload = _fallback_plan(command)
        else:
            payload = _fallback_plan(command)

    if not payload.task_id:
        payload.task_id = str(uuid.uuid4())
    payload.normalize_statuses()
    title = (payload.title or "").strip() or "Agent task"

    emode = (execution_mode or "paper").strip().lower()
    if emode not in ("paper", "live"):
        emode = "paper"
    rt = AgentPlanRuntime(
        payload=payload,
        user_id=user_id,
        organization_id=organization_id,
        original_command=command,
        os_key=os_key,
        correlation_id=correlation_id,
        execution_logs=[],
        execution_mode=emode,
    )
    _append_log(rt, "Plan generated — awaiting your approval for step 1.")
    with _lock:
        _persist_runtime(rt)

    out = _serialize_runtime(rt, title=title)
    if out.get("requires_approval"):
        _log.info(
            "agentic task_id=%s user_id=%s AWAITING_APPROVAL os_key=%s",
            payload.task_id,
            user_id,
            os_key,
        )
    return out


def get_plan(task_id: str, *, user_id: int) -> dict[str, Any] | None:
    row = fetch_task_row(task_id, user_id=user_id)
    if not row:
        return None
    rt = _load_runtime_from_row(row)
    if rt is None:
        return None
    out = _serialize_runtime(rt)
    try:
        from services.agent_stock_bridge import build_trade_step_preview

        idx = _next_pending_index(rt.payload.steps)
        if idx is not None and rt.payload.steps[idx].action == "trade":
            st = rt.payload.steps[idx]
            p = st.params if isinstance(st.params, dict) else {}
            sym = str(p.get("symbol") or "").strip().upper()
            if not sym:
                m = re.search(r"\b([A-Z]{3,15})\b", st.description.upper())
                sym = m.group(1) if m else ""
            if sym:
                out["trade_preview"] = build_trade_step_preview(rt.user_id, sym, p)
    except Exception as exc:
        out["trade_preview"] = {"ok": False, "error": str(exc)[:300]}
    return out


def _serialize_runtime(rt: AgentPlanRuntime, title: str | None = None) -> dict[str, Any]:
    p = rt.payload
    needs_approval = any(s.status == "pending_approval" for s in p.steps)
    cursor = _compute_current_step_index(p.steps)
    kill = False
    try:
        from services.broker.trading_guard import is_agent_trade_kill_active

        if rt.user_id > 0:
            kill = bool(is_agent_trade_kill_active(rt.user_id))
    except Exception:
        pass
    broker_hint = "PaperTradingAdapter"
    try:
        from services.broker.factory import get_broker_adapter

        broker_hint = get_broker_adapter(rt.user_id, execution_mode=rt.execution_mode or "paper").name
    except Exception:
        pass
    return {
        "ok": True,
        "task_id": p.task_id,
        "title": title or p.title or "Agent task",
        "os_key": rt.os_key,
        "original_command": rt.original_command,
        "requires_approval": needs_approval,
        "current_step_index": cursor,
        "steps": [s.model_dump(mode="json") for s in p.steps],
        "execution_logs": list(rt.execution_logs),
        "execution_mode": rt.execution_mode or "paper",
        "trade_kill_switch_active": kill,
        "effective_broker_adapter": broker_hint,
        "correlation_id": rt.correlation_id,
    }


def _next_pending_index(steps: list[PlanStepModel]) -> int | None:
    for i, s in enumerate(steps):
        if s.status == "pending_approval":
            return i
    return None


def _execute_step(
    rt: AgentPlanRuntime,
    step_index: int,
) -> tuple[bool, dict[str, Any]]:
    step = rt.payload.steps[step_index]
    action = step.action
    params = step.params if isinstance(step.params, dict) else {}
    uid = rt.user_id if rt.user_id > 0 else None
    oid = rt.organization_id

    log: Callable[[str], None] = lambda m: _append_log(rt, m)

    try:
        if action == "configure_system":
            uid_c = int(rt.user_id or 0)
            if uid_c <= 0:
                return False, {"error": "configure_system requires authenticated user"}
            intent = str(params.get("intent") or "").strip().lower()
            if intent == "disable_sentiment_today":
                out = set_sentiment_disabled_until_end_of_day_ist(uid_c)
                log("Sentiment overlay paused through end of day (IST); tokens never logged.")
                return True, {"ok": True, "intent": intent, **out}
            if intent == "enable_sentiment_overlay":
                set_user_runtime_kv(uid_c, "THIRAMAI_SENTIMENT_OVERLAY_ENABLED", "1")
                set_user_runtime_kv(uid_c, "THIRAMAI_SENTIMENT_RESUME_AT", "")
                log("Sentiment overlay re-enabled.")
                return True, {"ok": True, "intent": intent}
            if intent == "disable_smart_sizing":
                set_user_runtime_kv(uid_c, "THIRAMAI_SMART_SIZING_ENABLED", "0")
                log("Smart sizing disabled (no theta/sentiment lot tweaks).")
                return True, {"ok": True, "intent": intent}
            if intent == "enable_smart_sizing":
                set_user_runtime_kv(uid_c, "THIRAMAI_SMART_SIZING_ENABLED", "1")
                log("Smart sizing enabled.")
                return True, {"ok": True, "intent": intent}

            raw_key = str(params.get("env_key") or params.get("key") or "").strip()
            val_obj = params.get("value") if params.get("value") is not None else params.get("secret_value")
            if isinstance(val_obj, (int, float)):
                val_obj = str(val_obj)
            if not raw_key or val_obj is None:
                return False, {"error": "configure_system requires env_key+value or intent"}
            key = resolve_canonical_key(raw_key) or resolve_canonical_key(raw_key.upper())
            if not key:
                return False, {"error": "unknown_or_disallowed_key", "key": raw_key}
            val_s = str(val_obj).strip()
            saved = set_user_runtime_kv(uid_c, key, val_s)
            if not saved.get("ok"):
                return False, saved
            log(f"Saved {key} = {mask_for_log(key, val_s)}")
            extra: dict[str, Any] = {"configure": saved}
            if key in _KEYS_PROBE:
                from services.broker.probe import test_broker_connection

                probe = test_broker_connection(uid_c, execution_mode="live")
                extra["broker_validation"] = probe
                log(f"Broker validation (post-config): adapter={probe.get('broker')} ok={probe.get('ok')}")
            return True, {"ok": True, **extra}

        if action == "test_broker_connection":
            uid_t = int(rt.user_id or 0)
            if uid_t <= 0:
                return False, {"error": "test_broker_connection requires authenticated user"}
            from services.broker.probe import test_broker_connection

            hint = str(params.get("execution_hint") or params.get("mode") or "live").strip().lower()
            emode = hint if hint in ("paper", "live") else "live"
            probe = test_broker_connection(uid_t, execution_mode=emode)
            log(f"Broker probe: {probe.get('broker')} ok={probe.get('ok')}")
            return True, probe

        if action == "search":
            from services.research_common import snippets_blob_from_tavily, tavily_search_sync

            log("Starting Tavily web search...")
            q = str(params.get("query") or step.description or "").strip()
            if not q:
                return False, {"error": "search step missing params.query"}
            raw = tavily_search_sync(q, max_results=8)
            blob = snippets_blob_from_tavily(raw if isinstance(raw, dict) else {})
            log("Search complete; compiling snippets.")
            return True, {"ok": True, "mode": "tavily", "query": q, "snippets": blob[:12000], "raw_ok": isinstance(raw, dict)}

        if action == "trade":
            from datetime import date as date_cls
            from decimal import Decimal

            from services.agent_stock_bridge import option_lots_for_risk, run_equity_trade_bundle, smart_adjust_option_lots
            from services.options_chain_placeholder import (
                fetch_banknifty_option_chain_placeholder,
                fetch_nifty_option_chain_placeholder,
            )
            from services.research_common import market_sentiment_score_sync
            from services.stock_market_jarvis import get_index_snapshot_sync
            from services.trading.greeks_calculator import nifty_banknifty_option_greeks

            if rt.user_id and rt.user_id > 0:
                from services.broker.trading_guard import agent_trade_precheck

                ok_trade, blocked = agent_trade_precheck(rt.user_id)
                if not ok_trade:
                    log(f"Trade blocked: {blocked}")
                    return False, {"error": blocked or "trade_disabled", "kill_switch": True}

            sym = str(params.get("symbol") or "").strip().upper()
            if not sym:
                m = re.search(r"\b([A-Z]{3,15})\b", step.description.upper())
                sym = m.group(1) if m else ""
            if not sym:
                return False, {"error": "trade step missing symbol (params.symbol)"}

            depth = str(params.get("depth") or "full").strip().lower()
            out: dict[str, Any] = {"symbol": sym, "exchange_suffix": "NS"}

            if is_options_trade_context(sym, params):
                log("Fetching index spot for option context...")
                idx = get_index_snapshot_sync("^NSEI")
                spot = float(idx["last"]) if idx.get("ok") else None
                ch = str(params.get("chain") or "").lower()
                if ch == "banknifty" or sym == "BANKNIFTY":
                    log("Loading Bank Nifty option chain (placeholder service)...")
                    chain = fetch_banknifty_option_chain_placeholder(spot_hint=spot)
                    und_key = "banknifty"
                else:
                    log("Loading Nifty option chain (placeholder service)...")
                    chain = fetch_nifty_option_chain_placeholder(spot_hint=spot)
                    und_key = "nifty"
                log("Analyzing strikes for CE/PE recommendation (placeholder heuristic)...")
                log("Computing market sentiment (Tavily + Groq)...")
                sc_use: float | None = None
                if rt.user_id and rt.user_id > 0 and not smart_sizing_active(rt.user_id):
                    sent = {"ok": True, "skipped": True, "reason": "smart_sizing_disabled"}
                else:
                    sent = market_sentiment_score_sync(window_hours=2)
                    sc_use = float(sent["score"]) if sent.get("ok") else None
                    if rt.user_id and rt.user_id > 0 and not sentiment_overlay_active(rt.user_id):
                        sent = {**sent, "skipped": True, "reason": "sentiment_overlay_disabled"}
                        sc_use = None
                rec = chain.get("recommended") or {}
                prim = rec.get("primary") if isinstance(rec.get("primary"), dict) else {}
                prem = prim.get("premium_inr_per_share")
                lot_sz = int(chain.get("lot_size") or 65)
                spot_use = float(chain.get("spot_inr_approx") or spot or 24000)
                strike_k = float(prim.get("strike") or 0)
                right = str(prim.get("right") or "CE").upper()
                tech_bias = "BUY" if right == "CE" else "SELL"
                exp_raw = str(chain.get("expiry_next_weekly") or "")
                try:
                    ed = date_cls.fromisoformat(exp_raw[:10])
                    dte = float(max(1, (ed - date_cls.today()).days))
                except Exception:
                    dte = 5.0

                opt_out: dict[str, Any] = {
                    "ok": True,
                    "mode": "options_chain_placeholder",
                    "chain": chain,
                    "index_snapshot": idx,
                    "market_sentiment": sent,
                }
                if strike_k > 0 and prem is not None:
                    try:
                        greek = nifty_banknifty_option_greeks(
                            underlying=und_key,
                            spot_inr=spot_use,
                            strike_inr=strike_k,
                            days_to_expiry=dte,
                            right="CE" if right == "CE" else "PE",
                        )
                        opt_out["greeks"] = greek
                        log(
                            "Black-Scholes Greeks computed "
                            f"(delta={greek.get('delta')} theta/day={greek.get('theta_per_day')})."
                        )
                    except Exception as exc:
                        _log.debug("greeks skipped: %s", exc)

                if prem is not None and rt.user_id and rt.user_id > 0:
                    try:
                        prem_d = Decimal(str(prem))
                        log("Computing lot count from risk budget + smart sizing (theta/sentiment)...")
                        base_rs = option_lots_for_risk(
                            rt.user_id,
                            premium_per_share_inr=prem_d,
                            lot_size=lot_sz,
                        )
                        theta_pd = None
                        gk = opt_out.get("greeks")
                        if isinstance(gk, dict) and gk.get("theta_per_day") is not None:
                            theta_pd = float(gk["theta_per_day"])
                        sm = smart_adjust_option_lots(
                            base_rs.get("lots") or 0,
                            premium_per_share_inr=prem_d,
                            theta_per_day=theta_pd,
                            sentiment_score=sc_use,
                            technical_action=tech_bias,
                            user_id=rt.user_id,
                        )
                        opt_out["risk_sizing"] = {
                            **base_rs,
                            "lots_before_smart": base_rs.get("lots"),
                            "lots": sm.get("lots_adjusted"),
                            "smart_sizing": sm,
                        }
                    except Exception as exc:
                        _log.debug("option sizing skipped: %s", exc)
                log("Options execution not wired yet - Logging only")
                opt_out["order_execution"] = {
                    "skipped": True,
                    "reason": "options_not_wired",
                    "message": "Options execution not wired yet - Logging only",
                }
                return True, opt_out

            log(f"Fetching Nifty spot / live quote for {sym}...")
            bundle = run_equity_trade_bundle(
                sym,
                rt.user_id if rt.user_id > 0 else None,
                exchange_suffix="NS",
                depth=depth,
                log=log,
            )
            side_raw = str(params.get("side") or "").strip().lower()
            if side_raw in ("buy", "sell") and rt.user_id and rt.user_id > 0:
                rs = bundle.get("risk_sizing") if isinstance(bundle.get("risk_sizing"), dict) else {}
                qty_raw = rs.get("quantity_shares")
                try:
                    qty_i = int(qty_raw) if qty_raw is not None else 0
                except Exception:
                    qty_i = 0
                if _dry_run_force_qty_enabled():
                    qty_i = 1
                    log("THIRAMAI_DRY_RUN_FORCE_QTY active — quantity forced to 1.")
                q_data = bundle.get("quote") if isinstance(bundle.get("quote"), dict) else {}
                last_px = None
                if q_data.get("ok"):
                    try:
                        last_px = Decimal(str(q_data.get("last")))
                    except Exception:
                        last_px = None
                if qty_i <= 0:
                    log("Order skipped — zero risk-sized quantity.")
                    bundle["order_execution"] = {"skipped": True, "reason": "zero_quantity"}
                elif (last_px is None or last_px <= 0) and not _dry_run_force_qty_enabled():
                    log("Order skipped — no valid last price.")
                    bundle["order_execution"] = {"skipped": True, "reason": "no_price"}
                else:
                    from services.broker.factory import get_broker_adapter

                    broker = get_broker_adapter(rt.user_id, execution_mode=rt.execution_mode or "paper")
                    log(f"Routing {side_raw.upper()} x{qty_i} {sym} via {broker.name} ({rt.execution_mode})...")
                    px_for_order = last_px if last_px is not None and last_px > 0 else None
                    bundle["order_execution"] = broker.place_order(
                        symbol=sym,
                        side=side_raw,
                        quantity=qty_i,
                        price_inr=px_for_order,
                        exchange_suffix="NS",
                    )
                    _log_broker_order_id_if_present(rt, bundle["order_execution"])
            return True, bundle

        if action == "code":
            import brain

            log("Invoking council brain for code step...")
            instr = str(params.get("instruction") or step.description or "").strip()
            msg = f"[Agentic code step]\n{instr}"
            resp = brain.run_brain(msg, oid, user_id=uid, correlation_id=rt.correlation_id)
            log("Brain response received.")
            return True, {"ok": True, "mode": "code", "narrative": resp.narrative[:24000], "kind": getattr(resp, "kind", None)}

        import brain

        log("Reasoning step — consulting council brain...")
        q = str(params.get("question") or step.description or rt.original_command).strip()
        resp = brain.run_brain(q, oid, user_id=uid, correlation_id=rt.correlation_id)
        log("Brain response received.")
        return True, {"ok": True, "mode": "reason", "narrative": resp.narrative[:24000], "kind": getattr(resp, "kind", None)}
    except Exception as exc:
        _log.exception("step execute failed idx=%s action=%s", step_index, action)
        log(f"Step failed: {type(exc).__name__}")
        return False, {"error": type(exc).__name__, "detail": str(exc)[:2000]}


def _recovery_blocks(
    rt: AgentPlanRuntime,
    failed_index: int,
    err_payload: dict[str, Any],
) -> list[PlanStepModel]:
    step = rt.payload.steps[failed_index]
    system = (
        "A workflow step failed. Output JSON only: "
        '{"failure_summary": str, "suggested_fix": str, "recovery_steps": [ '
        '{"action": "search|trade|code|reason", "description": str, "params": {}} ]}'
        "Use 1–3 recovery_steps max. Be specific."
    )
    user_c = json.dumps(
        {
            "os_key": rt.os_key,
            "failed_action": step.action,
            "failed_description": step.description,
            "error": err_payload,
            "original_command": rt.original_command[:2000],
        },
        default=str,
    )[:14000]
    try:
        from services.research_common import groq_json_object_sync

        blob = groq_json_object_sync(system=system, user_content=user_c, max_tokens=2048)
        if not blob or not isinstance(blob, dict):
            return []
        raw_steps = blob.get("recovery_steps") or []
        out: list[PlanStepModel] = []
        base = max((s.step for s in rt.payload.steps), default=0)
        for i, rs in enumerate(raw_steps):
            if not isinstance(rs, dict):
                continue
            act = str(rs.get("action") or "reason").strip().lower()
            out.append(
                PlanStepModel(
                    step=base + i + 1,
                    action=act,
                    description=str(rs.get("description") or "Recovery step"),
                    status="queued",
                    params=rs.get("params") if isinstance(rs.get("params"), dict) else {},
                )
            )
        if out:
            out[0].status = "pending_approval"
            meta = {
                "failure_summary": blob.get("failure_summary"),
                "suggested_fix": blob.get("suggested_fix"),
            }
            out[0].params = {**meta, **(out[0].params or {})}
        return out
    except Exception as exc:
        _log.warning("recovery generation failed: %s", exc)
        return []


def approve_and_advance(
    task_id: str,
    *,
    user_id: int,
    signal: str = "success",
    execution_mode: str | None = None,
) -> dict[str, Any]:
    sig = (signal or "").strip().lower()
    with _lock:
        row = fetch_task_row(task_id, user_id=user_id)
        if not row:
            return {"ok": False, "error": "plan not found"}
        rt = _load_runtime_from_row(row)
        if rt is None:
            return {"ok": False, "error": "plan corrupt"}

        if execution_mode:
            em = str(execution_mode).strip().lower()
            if em in ("paper", "live") and em != (rt.execution_mode or "paper"):
                rt.execution_mode = em
                _append_log(rt, f"Execution mode for this run: {em}.")

        idx = _next_pending_index(rt.payload.steps)
        if idx is None:
            _append_log(rt, "No pending approvals — workflow idle or complete.")
            _persist_runtime(rt)
            return {
                "ok": True,
                "message": "no pending approval; plan may be complete",
                **_serialize_runtime(rt),
            }

        step = rt.payload.steps[idx]
        if sig in ("reject", "cancel", "no", "false"):
            step.status = "skipped"
            for j in range(idx + 1, len(rt.payload.steps)):
                if rt.payload.steps[j].status in ("queued", "pending_approval"):
                    rt.payload.steps[j].status = "skipped"
            _append_log(rt, "You rejected remaining steps.")
            _persist_runtime(rt)
            return {"ok": True, "message": "task rejected by user", **_serialize_runtime(rt)}

        if sig not in ("success", "approve", "ok", "yes", "true"):
            return {"ok": False, "error": "unknown signal; use success or reject"}

        step.status = "running"
        _append_log(rt, f"Executing step {step.step} ({step.action})...")
        _persist_runtime(rt)

        ok, result = _execute_step(rt, idx)
        if ok:
            step.status = "completed"
            step.params = {**(step.params or {}), "_result": result}
            for j in range(idx + 1, len(rt.payload.steps)):
                if rt.payload.steps[j].status == "queued":
                    rt.payload.steps[j].status = "pending_approval"
                    _append_log(rt, f"Step {step.step} done — awaiting approval for step {rt.payload.steps[j].step}.")
                    break
            else:
                _append_log(rt, "All steps completed.")
            _persist_runtime(rt)
            return {
                "ok": True,
                "message": "step completed",
                "last_result": result,
                **_serialize_runtime(rt),
            }

        step.status = "failed"
        step.params = {**(step.params or {}), "_failure": result}
        recovery = _recovery_blocks(rt, idx, result)
        if recovery:
            rt.payload.steps.extend(recovery)
            report = recovery[0].params or {}
            _append_log(rt, "Step failed — recovery path proposed; approval required.")
            _persist_runtime(rt)
            return {
                "ok": True,
                "message": "step failed — recovery path proposed; approval required",
                "failure_report": {
                    "failed_step": step.step,
                    "error": result,
                    "failure_summary": report.get("failure_summary"),
                    "suggested_fix": report.get("suggested_fix"),
                    "recovery_steps": [{"step": s.step, "action": s.action, "description": s.description} for s in recovery],
                },
                **_serialize_runtime(rt),
            }

        _persist_runtime(rt)
        return {
            "ok": False,
            "message": "step failed; no recovery generated",
            "failure": result,
            **_serialize_runtime(rt),
        }
