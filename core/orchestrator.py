"""Thin orchestration entry: vault → search → CEO → routed council → post steps."""

from __future__ import annotations

import os
from pathlib import Path

import asset_portal
import executive_core
from dotenv import load_dotenv
from groq import Groq
from tavily import TavilyClient

from core.context_engine import (
    build_executive_pack,
    build_shared_core,
    enrich_vault_for_query,
    load_vault_context_safe,
    vault_priority_search_context,
)
from core.council_runner import (
    repair_tamil_and_fluff,
    run_ceo_executive_pass,
    run_industrial_dpr_loop,
    run_manufacturing_empire_council,
    run_strategic_council,
    run_vault_personal_council,
    tamil_watch_violations,
)
from core.errors import QueryLengthExceeded, looks_like_length_limit_error
from core.kernel.reload_hook import maybe_log_pending_hot_reload
from core.swarm.pipeline import augment_shared_core_with_swarm, orchestrator_swarm_enabled
from core.observability import (
    LatencyTimer,
    clear_log_context,
    ensure_thiramai_logging,
    log_event,
    log_structured,
    new_request_id,
    set_log_context,
)
from core import recursive_learning
from core.sovereign_journal import record_background_action, record_cot_step
from core.routine_brief import try_routine_brief_only
from core.brain_output import (
    ActionIntentNone,
    BrainStructuredResponse,
    SellStockAction,
    parse_and_validate_brain_output,
    wrap_markdown_as_response,
)
from core.retail_sale_auth import role_may_execute_retail_sale
from core.sale_intent_heuristic import (
    early_retail_sell_quantity_veto_message,
    parsed_sell_intent_from_message,
    parsed_solar_research_intent_from_message,
    parsed_update_stock_intent_from_message,
)
from services.analytics_service import format_sales_analytics_markdown, user_requests_sales_analytics
from services.market_research_service import fetch_solar_dpr_research_bundle, format_solar_dpr_bundle_markdown
from services.empire_governance import maybe_apply_exception_only_ux
from services.sale_execution import execute_sell_stock_sync
from core.policies.loader import MAX_USER_MESSAGE_CHARS, get_prompt
from core.router import RouteMode, query_is_personal_vault_priority, resolve_route_mode
from core.search_pipeline import gather_live_search_context
from services.business_service import build_saas_factory_preview
from services.compliance_service import planning_note_text
from tools.registry import default_registry

_env_path = Path(".") / ".env"
load_dotenv(dotenv_path=_env_path, override=True)


def _ascii_debug(s: str, max_chars: int = 160) -> str:
    return ascii((s or "")[:max_chars])


def _orchestrator_brain_enabled() -> bool:
    """Opt-in layer; default off so existing deployments keep council-first behavior."""
    return (os.getenv("THIRAMAI_ORCHESTRATOR_BRAIN") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_flag_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _maybe_auto_execute_sell_stock(
    structured: BrainStructuredResponse,
    organization_id: int,
    *,
    actor_role_name: str | None,
    user_id: int | None = None,
    correlation_id: str | None = None,
    brain_user_message: str = "",
) -> BrainStructuredResponse:
    """
    When ``action_intent`` is ``sell_stock``, optionally run sale + bill (Phase 1 automation).

    Phase 2: only **admin** / **staff** (or ``THIRAMAI_RETAIL_SALE_ROLES``) may auto-execute.

    Controlled by ``THIRAMAI_AUTO_EXECUTE_SELL_STOCK`` (default: on). On success, appends a
    confirmation block to ``narrative`` and resets intent to ``none`` to avoid double execution.
    """
    if not isinstance(structured.action_intent, SellStockAction):
        return structured
    flag = (os.getenv("THIRAMAI_AUTO_EXECUTE_SELL_STOCK") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        note = (
            "\n\n---\n\n**Sell intent recorded** (auto-execution is off). "
            "Use HITL approval or enable `THIRAMAI_AUTO_EXECUTE_SELL_STOCK=1`."
        )
        return structured.model_copy(update={"narrative": structured.narrative + note})
    if not role_may_execute_retail_sale(actor_role_name):
        deny = (
            "\n\n---\n\n**Sale not executed:** retail sales require an **admin** or **staff** role "
            "(see tenant RBAC). Your current role cannot auto-post POS bills."
        )
        return structured.model_copy(
            update={"narrative": structured.narrative + deny, "action_intent": ActionIntentNone()}
        )
    intent = structured.action_intent
    igst = (os.getenv("THIRAMAI_RETAIL_GST_IGST") or "").strip().lower() in ("1", "true", "yes", "on")
    from api.dependencies import ROLE_LEVEL_BY_NAME

    uid = int(user_id) if user_id is not None and int(user_id) > 0 else None
    role_level = (
        ROLE_LEVEL_BY_NAME.get((actor_role_name or "customer").lower(), 5)
        if uid is not None
        else None
    )
    result = execute_sell_stock_sync(
        organization_id=int(organization_id),
        sku_name=intent.sku_name,
        quantity=float(intent.quantity),
        location=intent.location or "",
        interstate_gst=igst,
        principal_user_id=uid,
        principal_role_level=role_level,
        correlation_id=correlation_id,
    )
    try:
        from services.ltm_hooks import record_inventory_sell_execution

        record_inventory_sell_execution(
            organization_id=int(organization_id),
            prompt_context=brain_user_message or "",
            sku_name=intent.sku_name,
            quantity=float(intent.quantity),
            location=intent.location or "",
            result=result,
            correlation_id=correlation_id,
        )
    except Exception:
        pass
    if result.get("policy") == "PROPOSE":
        note = (
            "\n\n---\n\n**Pending approval (policy engine):** "
            f"{result.get('detail', 'Supervisor or owner confirmation required before posting this sale.')}"
        )
        return structured.model_copy(
            update={"narrative": structured.narrative + note, "action_intent": ActionIntentNone()}
        )
    if not result.get("ok"):
        tail = f"\n\n---\n\n**Sale not executed:** {result.get('error', 'unknown error')}"
        return structured.model_copy(
            update={"narrative": structured.narrative + tail, "action_intent": ActionIntentNone()}
        )
    tail = (
        f"\n\n---\n\n**Sale completed** · Bill **#{result['bill_id']}** · "
        f"Total **₹{result['total_amount']:.2f}** · "
        f"`{result['sku_name']}` × **{result['quantity_sold']}** · "
        f"Remaining stock: **{result['remaining_quantity']:.4f}**"
    )
    return structured.model_copy(
        update={"narrative": structured.narrative + tail, "action_intent": ActionIntentNone()}
    )


def _jarvis_think(message: str, *, phase: str, request_id: str | None = None) -> None:
    try:
        from services.thought_stream import append_thought

        append_thought(message, phase=phase, agent="orchestrator", request_id=request_id)
    except Exception:
        pass


def run_brain(
    user_message: str,
    organization_id: int,
    *,
    actor_role_name: str | None = None,
    user_id: int | None = None,
    vault_passphrase: str | None = None,
    correlation_id: str | None = None,
) -> BrainStructuredResponse:
    """
    Run the full brain pipeline for one tenant.

    organization_id is mandatory: vault + DB context never mix other organizations' data.
    ``actor_role_name`` is the authenticated user's role (for ``sell_stock`` RBAC); omit for CLI/scripts.
    ``user_id`` + ``vault_passphrase`` enable **Life OS** context (daily planner, encrypted notes) in the pack.

    Returns a validated **BrainStructuredResponse**: `narrative` (Markdown for the user) and
    `action_intent` (discriminated union: none | create_invoice | order_stock | update_stock | sell_stock
    | trigger_solar_research).

    When ``THIRAMAI_ORCHESTRATOR_BRAIN=1``, a thin intent/tool path may return early (council unchanged
    as fallback). System autonomy uses ``THIRAMAI_ORCHESTRATOR_AUTO_MODE`` and ``THIRAMAI_ORCHESTRATOR_TRIGGER=system``.
    """
    ensure_thiramai_logging()
    request_id = new_request_id()
    timer = LatencyTimer()
    route_tag = "preflight"
    outcome_text = ""
    structured_parse_ok = False
    brain_error: BaseException | None = None
    raw = ""
    org_id = int(organization_id)
    set_log_context(trace_id=request_id, organization_id=org_id)
    maybe_log_pending_hot_reload(request_id=request_id)

    try:
        log_structured(
            "orchestrator.session_start",
            request_id=request_id,
            groq_configured=bool((os.getenv("GROQ_API_KEY") or "").strip()),
        )
        record_cot_step(
            agent="orchestrator",
            phase="session_start",
            detail=f"message_chars={len((user_message or '').strip())}",
            organization_id=org_id,
            trace_id=request_id,
        )
        _jarvis_think(
            f"Session started; analyzing request ({len((user_message or '').strip())} chars).",
            phase="session_start",
            request_id=request_id,
        )

        raw = (user_message or "").strip()
        if len(raw) > MAX_USER_MESSAGE_CHARS:
            log_structured(
                "orchestrator.message_clipped",
                request_id=request_id,
                original_chars=len(raw),
                clipped_to=MAX_USER_MESSAGE_CHARS,
            )
            raw = raw[:MAX_USER_MESSAGE_CHARS]

        veto = early_retail_sell_quantity_veto_message(raw)
        if veto:
            outcome_text = veto
            route_tag = "preflight_veto"
            log_event(
                request_id,
                "orchestrator.retail_quantity_veto",
                ok=True,
                latency_ms=timer.ms(),
                extra={"organization_id": org_id},
            )
            _jarvis_think(
                "Preflight: retail quantity guard triggered; short-circuiting to safe reply.",
                phase="preflight",
                request_id=request_id,
            )
            return BrainStructuredResponse(narrative=veto, action_intent=ActionIntentNone())

        executive_core.ensure_vault()
        executive_core.ingest_epa_tags(raw)

        routine_out = try_routine_brief_only(
            raw,
            org_id,
            actor_role_name=actor_role_name,
            user_id=user_id,
            correlation_id=correlation_id,
        )
        if routine_out is not None:
            route_tag = "routine_brief"
            outcome_text = routine_out.narrative
            log_structured(
                "orchestrator.routine_brief",
                request_id=request_id,
                organization_id=org_id,
            )
            try:
                executive_core.append_daily_log(
                    f"Routine brief | in_chars={len(raw)} | req={request_id}"
                )
            except OSError:
                pass
            log_event(
                request_id,
                "orchestrator.complete",
                ok=True,
                latency_ms=timer.ms(),
                extra={
                    "route": route_tag,
                    "out_chars": len(routine_out.narrative),
                    "organization_id": org_id,
                    "structured_parse_ok": True,
                },
            )
            record_cot_step(
                agent="orchestrator",
                phase="routine_brief",
                detail=f"route={route_tag} out_chars={len(routine_out.narrative)}",
                organization_id=org_id,
                trace_id=request_id,
            )
            _jarvis_think(
                "Routine brief path matched; returning deterministic ops snippet (no full council).",
                phase="routine_brief",
                request_id=request_id,
            )
            return routine_out

        if _orchestrator_brain_enabled():
            from core.orchestrator_brain import run_orchestrator_brain

            try:
                from api.dependencies import ROLE_LEVEL_BY_NAME

                rl = int(ROLE_LEVEL_BY_NAME.get((actor_role_name or "customer").lower(), 5))
            except Exception:
                rl = 5
            brain_ctx: dict = {
                "organization_id": org_id,
                "actor_role_name": actor_role_name,
                "user_id": user_id,
                "correlation_id": correlation_id,
                "auto_mode": _env_flag_truthy("THIRAMAI_ORCHESTRATOR_AUTO_MODE"),
                "trigger": str(os.getenv("THIRAMAI_ORCHESTRATOR_TRIGGER") or "user").strip().lower()
                or "user",
                "role_level": rl,
            }
            try:
                ob = run_orchestrator_brain(raw, brain_ctx, request_id=request_id)
            except Exception as exc:
                log_structured(
                    "orchestrator_brain.exception",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                    error_snippet=_ascii_debug(str(exc), 240),
                )
                ob = {"handled": False, "fallback_reason": "brain_exception"}
            if ob.get("handled") and ob.get("brain_response") is not None:
                structured = ob["brain_response"]
                route_tag = "orchestrator_brain"
                outcome_text = structured.narrative
                structured_parse_ok = True
                log_structured(
                    "orchestrator_brain.handled",
                    request_id=request_id,
                    organization_id=org_id,
                    mode=ob.get("mode"),
                    status=ob.get("status"),
                )
                try:
                    executive_core.append_daily_log(
                        f"Orchestrator brain | mode={ob.get('mode')} | in_chars={len(raw)} | req={request_id}"
                    )
                except OSError:
                    pass
                log_event(
                    request_id,
                    "orchestrator.complete",
                    ok=True,
                    latency_ms=timer.ms(),
                    extra={
                        "route": route_tag,
                        "out_chars": len(structured.narrative),
                        "organization_id": org_id,
                        "structured_parse_ok": structured_parse_ok,
                        "orchestrator_brain": True,
                    },
                )
                record_cot_step(
                    agent="orchestrator",
                    phase="orchestrator_brain",
                    detail=f"mode={ob.get('mode')} action={ob.get('action')}",
                    organization_id=org_id,
                    trace_id=request_id,
                )
                _jarvis_think(
                    f"Orchestrator brain short-circuit (mode={ob.get('mode')}); returning tool/narrative bundle.",
                    phase="orchestrator_brain",
                    request_id=request_id,
                )
                record_background_action(
                    category="orchestrator",
                    summary=f"Orchestrator brain mode={ob.get('mode')} latency_ms={timer.ms():.0f}",
                    organization_id=org_id,
                    meta={"request_id": request_id, "orchestrator_brain": True},
                )
                structured = maybe_apply_exception_only_ux(
                    structured,
                    route_tag=route_tag,
                    user_message=raw,
                    structured_parse_ok=structured_parse_ok,
                )
                outcome_text = structured.narrative
                return structured

        groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
        tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()
        if not groq_key:
            raise RuntimeError("GROQ_API_KEY is missing. Add it to `.env` in the project folder.")
        if not tavily_key:
            raise RuntimeError("TAVILY_API_KEY is missing. Add it to `.env` in the project folder.")

        _jarvis_think(
            "API keys validated; gathering live search context, vault, and executive pack.",
            phase="context",
            request_id=request_id,
        )

        personal_vault = query_is_personal_vault_priority(raw)
        registry = default_registry(request_id)
        client = Groq(api_key=groq_key)
        tavily = TavilyClient(api_key=tavily_key)

        try:
            if personal_vault:
                context_block, _has_hits = vault_priority_search_context()
                log_structured("orchestrator.tavily_skipped", request_id=request_id, reason="personal_vault_priority")
            else:
                context_block, _has_hits = gather_live_search_context(registry, tavily, client, raw)
        except QueryLengthExceeded:
            raise
        except Exception as exc:
            if looks_like_length_limit_error(exc):
                raise QueryLengthExceeded(
                    "The search request was too long for the provider. "
                    "Try a shorter brief (under 5000 characters) or simplify your topic."
                ) from exc
            raise

        vault_ctx = load_vault_context_safe(raw, max_chars=None, organization_id=org_id)
        vault_ctx = enrich_vault_for_query(raw, vault_ctx, organization_id=org_id)
        executive_pack = build_executive_pack(
            raw,
            vault_ctx,
            organization_id=org_id,
            user_id=user_id,
            vault_passphrase=vault_passphrase,
        )

        try:
            ceo_brief = run_ceo_executive_pass(registry, client, raw, executive_pack)
        except QueryLengthExceeded:
            raise

        log_structured("orchestrator.executive_core_ready", request_id=request_id)

        route_mode, route_label = resolve_route_mode(raw)
        log_structured("orchestrator.route_selected", request_id=request_id, route_label=route_label)
        record_cot_step(
            agent="orchestrator",
            phase="route",
            detail=str(route_label),
            organization_id=org_id,
            trace_id=request_id,
        )
        _jarvis_think(
            f"Route debate resolved: {route_label} — preparing {route_tag} council.",
            phase="route",
            request_id=request_id,
        )

        saas_preview = build_saas_factory_preview()
        planning_note = planning_note_text()
        try:
            from services import project_engine as _factory_os

            _fos = _factory_os.build_factory_os_council_appendix(org_id)
            if _fos.strip():
                planning_note = _fos.strip() + "\n\n" + planning_note
        except Exception:
            pass

        shared_core = build_shared_core(
            ceo_brief=ceo_brief,
            vault_ctx=vault_ctx,
            saas_preview=saas_preview,
            raw=raw,
            context_block=context_block,
            planning_note=planning_note,
            personal_vault=personal_vault,
        )

        if orchestrator_swarm_enabled():
            from api.dependencies import ROLE_LEVEL_BY_NAME
            from services.billing_guard import is_billing_paused

            rl = ROLE_LEVEL_BY_NAME.get((actor_role_name or "customer").lower(), 5)
            shared_core = augment_shared_core_with_swarm(
                shared_core,
                user_message=raw,
                organization_id=org_id,
                request_id=request_id,
                user_role_level=int(rl),
                billing_paused=bool(is_billing_paused(org_id)),
                actor_role_name=actor_role_name,
            )

        final_raw = ""

        _jarvis_think(
            f"Running strategy pipeline ({route_label}) — council synthesis in flight.",
            phase="council",
            request_id=request_id,
        )

        try:
            if route_mode is RouteMode.INDUSTRIAL_DPR:
                final_raw, _ = run_industrial_dpr_loop(registry, client, shared_core)
                route_tag = "DPR"
            elif route_mode is RouteMode.MANUFACTURING_EMPIRE:
                final_raw = run_manufacturing_empire_council(registry, client, shared_core)
                route_tag = "ManufacturingEmpire"
            elif route_mode is RouteMode.PERSONAL_VAULT:
                final_raw = run_vault_personal_council(registry, client, shared_core)
                route_tag = "PersonalVault"
            else:
                final_raw = run_strategic_council(registry, client, shared_core)
                route_tag = "AgriCouncil"
        except QueryLengthExceeded:
            raise
        except Exception as exc:
            log_event(
                request_id,
                "orchestrator.council_failed",
                ok=False,
                error=str(exc),
                latency_ms=timer.ms(),
                extra={"organization_id": org_id},
            )
            try:
                from services.thought_stream import append_exception_thought

                append_exception_thought(
                    exc,
                    prefix="Council pipeline error (full message for operators):",
                    phase="council",
                    agent="orchestrator",
                    request_id=request_id,
                    with_traceback=True,
                )
            except Exception:
                pass
            final_raw = (
                f"**Partial response:** the strategy pipeline hit an unexpected error ({type(exc).__name__}). "
                "Try again with a shorter brief or check API keys and connectivity."
            )
            route_tag = "ErrorFallback"
            _jarvis_think(
                "Council stage encountered an error; serving sanitized fallback narrative.",
                phase="council",
                request_id=request_id,
            )

        if not final_raw.strip():
            _jarvis_think(
                "Model returned an empty body; emitting awaiting-data placeholder.",
                phase="council",
                request_id=request_id,
            )
            empty = BrainStructuredResponse(
                narrative="**Awaiting Live Data** - model returned an empty response.",
                action_intent=ActionIntentNone(),
            )
            outcome_text = empty.narrative
            return empty

        _jarvis_think(
            f"Draft received from {route_tag}; parsing structured output / wrapping markdown.",
            phase="parse",
            request_id=request_id,
        )

        if route_mode is RouteMode.INDUSTRIAL_DPR:
            structured = wrap_markdown_as_response(final_raw)
            structured_parse_ok = False
        else:
            structured, structured_parse_ok = parse_and_validate_brain_output(final_raw)

        if isinstance(structured.action_intent, ActionIntentNone):
            hinted = parsed_sell_intent_from_message(raw)
            if hinted is not None:
                structured = structured.model_copy(update={"action_intent": hinted})
                structured_parse_ok = True
            else:
                add_hint = parsed_update_stock_intent_from_message(raw)
                if add_hint is not None:
                    structured = structured.model_copy(update={"action_intent": add_hint})
                    structured_parse_ok = True
                else:
                    sol = parsed_solar_research_intent_from_message(raw)
                    if sol is not None:
                        try:
                            bundle = fetch_solar_dpr_research_bundle(force_refresh=sol.force_refresh)
                            md = format_solar_dpr_bundle_markdown(bundle)
                            structured = structured.model_copy(
                                update={
                                    "narrative": structured.narrative.rstrip() + "\n\n---\n\n" + md,
                                    "action_intent": sol,
                                }
                            )
                            structured_parse_ok = True
                        except Exception as exc:
                            log_structured(
                                "orchestrator.solar_research_failed",
                                request_id=request_id,
                                error_type=type(exc).__name__,
                                error_snippet=_ascii_debug(str(exc), 240),
                            )
                            structured = structured.model_copy(
                                update={
                                    "narrative": structured.narrative.rstrip()
                                    + f"\n\n---\n\n**Solar research:** could not complete ({type(exc).__name__}).",
                                    "action_intent": sol,
                                }
                            )
                            structured_parse_ok = True

        need_morning, today_iso = executive_core.morning_brief_pending_today()
        if need_morning:
            structured = structured.model_copy(
                update={
                    "narrative": executive_core.build_sovereign_morning_brief()
                    + "\n"
                    + structured.narrative
                }
            )
            try:
                executive_core.mark_morning_brief_shown(today_iso)
            except OSError:
                pass

        structured = _maybe_auto_execute_sell_stock(
            structured,
            org_id,
            actor_role_name=actor_role_name,
            user_id=user_id,
            correlation_id=correlation_id,
            brain_user_message=raw,
        )

        if user_requests_sales_analytics(raw):
            try:
                thr_raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
                try:
                    thr = max(0, min(10_000, int(thr_raw)))
                except ValueError:
                    thr = 5
                analytics_md = format_sales_analytics_markdown(org_id, low_stock_threshold=thr)
                structured = structured.model_copy(
                    update={
                        "narrative": structured.narrative.rstrip() + "\n\n---\n\n" + analytics_md,
                    }
                )
            except Exception as exc:
                log_event(
                    request_id,
                    "orchestrator.sales_analytics_failed",
                    ok=False,
                    error=str(exc),
                    latency_ms=timer.ms(),
                    extra={"organization_id": org_id},
                )

        tamil_system = f"{get_prompt('TAMIL_REPAIR_SYSTEM')}\n\n{get_prompt('ANTI_REPEAT')}"
        if tamil_watch_violations(structured.narrative):
            _jarvis_think(
                "Language guard triggered; polishing narrative (Tamil / anti-repeat pass).",
                phase="polish",
                request_id=request_id,
            )
            try:
                repaired = repair_tamil_and_fluff(
                    registry, client, tamil_system, structured.narrative
                )
                if repaired and len(repaired) >= min(len(structured.narrative) * 0.3, 200):
                    structured = structured.model_copy(update={"narrative": repaired})
                else:
                    log_structured(
                        "orchestrator.tamil_repair_skipped",
                        request_id=request_id,
                        reason="empty_or_short_output",
                    )
            except QueryLengthExceeded:
                raise
            except Exception as exc:
                log_structured(
                    "orchestrator.tamil_repair_failed",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                    error_snippet=_ascii_debug(str(exc), 240),
                )

        if personal_vault:
            try:
                asset_md = asset_portal.format_recent_factory_assets_markdown_for_personal(
                    organization_id=org_id, limit=8, within_hours=168
                )
                if asset_md:
                    structured = structured.model_copy(
                        update={"narrative": structured.narrative.rstrip() + "\n\n---\n\n" + asset_md}
                    )
            except Exception as exc:
                log_structured(
                    "orchestrator.asset_markdown_skipped",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                    error_snippet=_ascii_debug(str(exc), 120),
                )

        try:
            executive_core.append_daily_log(
                f"Strategic run complete | route={route_tag} | in_chars={len(raw)} | req={request_id}"
            )
        except OSError:
            pass

        log_event(
            request_id,
            "orchestrator.complete",
            ok=True,
            latency_ms=timer.ms(),
            extra={
                "route": route_tag,
                "out_chars": len(structured.narrative),
                "organization_id": org_id,
                "structured_parse_ok": structured_parse_ok,
            },
        )
        record_cot_step(
            agent="orchestrator",
            phase="council_complete",
            detail=f"route={route_tag} parse_ok={structured_parse_ok}",
            organization_id=org_id,
            trace_id=request_id,
        )
        _jarvis_think(
            f"Council complete ({route_tag}); packaging response for user.",
            phase="complete",
            request_id=request_id,
        )
        record_background_action(
            category="orchestrator",
            summary=f"Brain run complete route={route_tag} latency_ms={timer.ms():.0f}",
            organization_id=org_id,
            meta={"request_id": request_id, "structured_parse_ok": structured_parse_ok},
        )
        structured = maybe_apply_exception_only_ux(
            structured,
            route_tag=route_tag,
            user_message=raw,
            structured_parse_ok=structured_parse_ok,
        )
        outcome_text = structured.narrative
        return structured
    except QueryLengthExceeded as e:
        brain_error = e
        if not outcome_text:
            outcome_text = str(e)[:500]
        raise
    except RuntimeError as e:
        brain_error = e
        raise
    except Exception as e:
        brain_error = e
        if not outcome_text:
            outcome_text = f"uncaught:{type(e).__name__}"
        raise
    finally:
        recursive_learning.run_post_mortem(
            request_id=request_id,
            route_tag=route_tag,
            outcome_text=outcome_text,
            error=brain_error,
            user_message=raw or (user_message or "").strip(),
            latency_ms=timer.ms(),
            organization_id=org_id,
        )
        clear_log_context()
