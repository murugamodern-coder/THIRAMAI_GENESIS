"""Per-step self-heal loop, verification, and trace (action execution perfection layer)."""

from __future__ import annotations

import time
from typing import Any, Callable

from services.action_plugins import run_plugin
from services.browser_automation_controller import BrowserAutomationController
from services.execution_memory_store import record_failure_pattern, record_outcome
from services.execution_self_healing import apply_self_heal_strategy, classify_error
from services.execution_verification import verify_step_outcome

MAX_HEAL_ROUNDS = 3


def _exec_meta(result: dict[str, Any], *, state: str, round_i: int) -> dict[str, Any]:
    ex = {**(result.get("execution") or {}), "state": state, "round": round_i + 1, "max_rounds": MAX_HEAL_ROUNDS}
    return {**result, "execution": ex}


def _dispatch_browser(b: BrowserAutomationController, step_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    to = int(float(payload.get("timeout_ms") or payload.get("__heal_increase_timeout") or 45_000))
    to = min(120_000, max(5_000, to))
    if not b.available() or not b._page:
        return {"ok": False, "error": "playwright not installed" if not b.available() else "no active page"}
    if step_kind == "browser_open":
        url = str(payload.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "url required"}
        if payload.get("__heal_reload_first"):
            b.reload_page(timeout_ms=to)
        return b.open_url(url, timeout_ms=to)
    if step_kind == "browser_search":
        if payload.get("__heal_reload_first") and b._page:
            b.reload_page(timeout_ms=to)
        return b.search(
            str(payload.get("query") or ""),
            base_url=(payload.get("base_url") or None),
            timeout_ms=to,
        )
    if step_kind == "browser_click":
        main = str(payload.get("selector") or "").strip()
        rest = [str(x) for x in (payload.get("selector_fallbacks") or []) if str(x).strip()]
        cands = ([main] if main else []) + [x for x in rest if x != main]
        if payload.get("_try_all_selectors", True) and len(cands) > 1:
            return b.try_click_selectors(cands, timeout_ms=min(to, 60_000))
        if not cands:
            return {"ok": False, "error": "selector required"}
        return b.click(cands[0], timeout_ms=min(to, 60_000))
    if step_kind == "browser_fill":
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        return b.fill_form({str(k): str(v) for k, v in fields.items()}, timeout_ms=min(to, 60_000))
    return {"ok": False, "error": f"unknown browser op: {step_kind}"}


def _try_email_notify_fallback(
    payload: dict[str, Any],
    org_id: int,
) -> dict[str, Any]:
    n = run_plugin(
        "notify",
        {
            "title": str(payload.get("notify_title") or payload.get("subject") or "Action notice")[:300],
            "body": str(payload.get("notify_body") or payload.get("body") or "Email could not be sent; see details.")[:4000],
            "severity": str(payload.get("notify_severity") or "warning")[:16],
        },
        organization_id=int(org_id),
    )
    n = dict(n) if isinstance(n, dict) else {"ok": False, "error": "notify"}
    n["email_fallback"] = True
    n["fallback_notification_ok"] = bool(n.get("ok") or n.get("simulated"))
    n["ok"] = n["fallback_notification_ok"]
    return n


def run_step_with_perfection(
    step_order: int,
    phase: str,
    step_kind: str,
    risk: str,
    payload: dict[str, Any],
    ctx: Any,
    dispatch_non_browser: Callable[[str, dict[str, Any], Any], dict[str, Any]],
) -> dict[str, Any]:
    """
    Execute→verify with up to ``MAX_HEAL_ROUNDS`` self-heal cycles.

    Stabilizer: on failure, applies strategies before giving up. Email can fall back to in-app notification.
    """
    t0 = time.monotonic()
    p: dict[str, Any] = dict(payload)
    trace: list[dict[str, Any]] = []
    last: dict[str, Any] = {"ok": False, "error": "not executed"}
    verified, vdetail = False, {}
    total_retries = 0
    sk = str(step_kind or "")
    internal = sk.startswith("internal_")
    rounds = 1 if internal else MAX_HEAL_ROUNDS
    p["_try_all_selectors"] = True

    if sk.startswith("browser_"):
        with BrowserAutomationController() as b:
            if not b.available():
                last = {"ok": False, "error": "playwright not available"}
            else:
                for round_i in range(rounds):
                    if round_i > 0:
                        ec = classify_error(last, sk)
                        p, strat, sctx = apply_self_heal_strategy(sk, p, ec, round_i - 1)
                        trace.append({"round": round_i, "error_class": ec, "strategy": strat, "detail": sctx})
                        total_retries += 1
                        p["_try_all_selectors"] = round_i < 1
                    last = _exec_meta(_dispatch_browser(b, sk, p), state="verifying", round_i=round_i)
                    verified, vdetail = verify_step_outcome(sk, last, p)
                    if verified:
                        last = {**last, "verify_detail": vdetail}
                        break
    else:
        for round_i in range(rounds):
            if round_i > 0:
                ec = classify_error(last, sk)
                p, strat, sctx = apply_self_heal_strategy(sk, p, ec, round_i - 1)
                trace.append({"round": round_i, "error_class": ec, "strategy": strat, "detail": sctx})
                total_retries += 1
            last = _exec_meta(dispatch_non_browser(sk, p, ctx), state="verifying", round_i=round_i)
            verified, vdetail = verify_step_outcome(sk, last, p)
            if verified:
                last = {**last, "verify_detail": vdetail}
                break
            if sk in ("plugin_email", "email") and p.get("fallback_to_notify") and round_i == rounds - 1:
                last = _try_email_notify_fallback(p, int(ctx.organization_id))
                last = _exec_meta(last, state="verifying", round_i=round_i)
                verified, vdetail = verify_step_outcome("plugin_email", last, p)
                if verified:
                    last = {**last, "verify_detail": vdetail}
                break

    ok = bool(verified)
    elapsed = time.monotonic() - t0
    if ok and trace:
        outcome = "recovered"
    elif ok:
        outcome = "success"
    else:
        outcome = "failed"

    record_outcome(
        user_id=int(ctx.user_id),
        organization_id=int(ctx.organization_id),
        step_kind=sk,
        payload=dict(payload),
        success=ok,
        summary=str(last.get("error") or last.get("summary") or ("ok" if ok else "failed"))[:500],
        detail={"result": last, "heal_trace": trace, "verify_detail": vdetail},
    )
    if not ok:
        record_failure_pattern(
            user_id=int(ctx.user_id),
            organization_id=int(ctx.organization_id),
            step_kind=sk,
            payload=dict(payload),
            error_class=classify_error(last, sk),
            message=str(last.get("error") or "")[:800],
            heal_trace=trace,
        )

    return {
        "step_order": step_order,
        "phase": phase,
        "step_kind": sk,
        "risk_level": risk,
        "result": last,
        "outcome": outcome,
        "verified": ok,
        "verify_detail": vdetail,
        "heal_trace": trace,
        "retries": total_retries,
        "attempts": 1 + total_retries,
        "elapsed_s": round(elapsed, 3),
        "ok": ok,
    }
