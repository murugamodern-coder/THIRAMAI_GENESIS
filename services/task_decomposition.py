"""Turn a natural-language command into phased plan steps: search → analyze → decide → act."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s\]>\"']+", re.I)
_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)


def _urls_in(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in _URL_RE.finditer(text or "")))


def _emails_in(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in _EMAIL_RE.finditer(text or "")))


def scan_context_hints(command: str) -> dict[str, Any]:
    """Public helper for internal search steps (URLs / emails extracted from text)."""
    cmd = str(command or "")
    return {"urls": _urls_in(cmd), "emails": _emails_in(cmd)}


def _wants_browser(text: str) -> bool:
    t = (text or "").lower()
    return bool(_urls_in(text)) or any(
        k in t
        for k in (
            "open ",
            "browse ",
            "navigate ",
            "visit ",
            "go to ",
            "goto ",
            "click ",
            "fill ",
            "form ",
            "login ",
            "website",
            "browser",
        )
    )


def _wants_email(text: str) -> bool:
    t = (text or "").lower()
    return "email" in t or "e-mail" in t or "smtp" in t or ("send " in t and "mail" in t)


def _wants_file(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("write file", "create file", "save to ", "save file", "export ", ".md", ".txt", ".csv"))


def _wants_api(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("http ", "https ", "api ", "webhook", "rest ", "post to ", "get from "))


def _wants_notify(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("notify", "notification", "alert me", "ping ", "remind "))


def _extract_api_target(text: str) -> str | None:
    for u in _urls_in(text):
        if "api" in u.lower() or "/webhook" in u.lower():
            return u
    return _urls_in(text)[0] if _urls_in(text) else None


def _split_sub_goals(raw: str) -> list[str]:
    # Lightweight intent decomposition from separators and action cues.
    parts = re.split(r"\b(?:then|and then|after that|next|also|;|\.|\n)\b", raw, flags=re.I)
    out: list[str] = []
    for p in parts:
        s = str(p or "").strip(" -,:")
        if len(s) >= 6:
            out.append(s[:300])
    if not out and raw.strip():
        out = [raw.strip()[:300]]
    return out[:8]


def _infer_dependencies(sub_goals: list[str]) -> list[dict[str, Any]]:
    deps: list[dict[str, Any]] = []
    for idx, sg in enumerate(sub_goals):
        if idx == 0:
            deps.append({"sub_goal": sg, "depends_on": []})
        else:
            deps.append({"sub_goal": sg, "depends_on": [sub_goals[idx - 1][:120]]})
    return deps


def _is_complex_command(raw: str, sub_goals: list[str]) -> bool:
    t = (raw or "").lower()
    signal_words = ("workflow", "pipeline", "end-to-end", "multi", "sequence", "steps", "automate")
    signals = sum(1 for w in signal_words if w in t)
    return len(sub_goals) >= 3 or (len(sub_goals) >= 2 and len(raw) > 120) or signals >= 2 or len(raw) > 240


def _build_reasoning_depth(raw: str) -> dict[str, Any]:
    sub_goals = _split_sub_goals(raw)
    deps = _infer_dependencies(sub_goals)
    complex_cmd = _is_complex_command(raw, sub_goals)
    workflow_type = "multi_step" if complex_cmd else "single_path"
    return {
        "sub_goals": sub_goals,
        "dependencies": deps,
        "multi_step_workflow": bool(complex_cmd),
        "workflow_type": workflow_type,
    }


def _validation_for_step(step_kind: str) -> dict[str, Any]:
    sk = str(step_kind or "")
    if sk.startswith("browser_"):
        return {"check": "page_or_element_state", "strict": False}
    if sk.startswith("plugin_api"):
        return {"check": "http_status_or_response_shape", "strict": True}
    if sk.startswith("plugin_email"):
        return {"check": "delivery_or_notification_fallback", "strict": False}
    if sk.startswith("plugin_file"):
        return {"check": "path_written", "strict": True}
    return {"check": "result_ok", "strict": False}


def _plan_confidence(raw: str, steps: list[dict[str, Any]], reasoning: dict[str, Any]) -> float:
    if not steps:
        return 0.0
    n = len(steps)
    has_urls = bool(_urls_in(raw))
    has_targets = any(str(s.get("step_kind") or "").startswith(("plugin_api", "browser_")) for s in steps)
    complexity_pen = 0.10 if reasoning.get("multi_step_workflow") else 0.0
    base = 0.62 + (0.04 if has_urls else 0.0) + (0.04 if has_targets else 0.0) - min(0.18, max(0, n - 6) * 0.02) - complexity_pen
    return max(0.05, min(0.98, round(base, 3)))


def _ensure_deep_planning_contract(
    *,
    raw: str,
    steps: list[dict[str, Any]],
    reasoning: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    P2.5 deep planning contract for complex commands:
    - enforce >=3 act steps
    - enforce >=2 explicit alternative paths
    - enforce research -> compare -> decide -> execute chain markers
    """
    if not bool(reasoning.get("multi_step_workflow")):
        return steps
    out = list(steps)
    if not out:
        return out
    # chain anchors (no new step kinds introduced; use existing internal types)
    has_compare = any(
        str((s.get("payload") or {}).get("reasoning_stage") or "") == "compare"
        for s in out
        if isinstance(s, dict)
    )
    if not has_compare:
        order = max(int(s.get("step_order") or 0) for s in out) + 1
        out.append(
            {
                "step_order": order,
                "phase": "analyze",
                "step_kind": "internal_command_analysis",
                "risk_level": "low",
                "payload": {
                    "command": raw,
                    "reasoning_stage": "compare",
                    "subtask": "Compare options with explicit tradeoffs",
                    "validation": _validation_for_step("internal_command_analysis"),
                    "branching_paths": [
                        {"branch_id": "primary", "goal": "best_expected_value"},
                        {"branch_id": "fallback", "goal": "minimize_downside"},
                    ],
                },
            }
        )
    act_rows = [s for s in out if str(s.get("phase") or "") == "act"]
    next_order = max(int(s.get("step_order") or 0) for s in out) + 1
    while len(act_rows) < 3:
        filler_kind = "plugin_notify" if len(act_rows) % 2 == 0 else "internal_summarize"
        payload: dict[str, Any]
        if filler_kind == "plugin_notify":
            payload = {
                "title": "Execution checkpoint",
                "body": "Complex workflow checkpoint; validate prior act step before continuing.",
                "severity": "info",
            }
        else:
            payload = {
                "command": raw,
                "message": "Fallback execution summary for complex chain continuity.",
            }
        row = {
            "step_order": next_order,
            "phase": "act",
            "step_kind": filler_kind,
            "risk_level": "low",
            "payload": {
                **payload,
                "reasoning_stage": "execute",
                "branching_paths": [
                    {"branch_id": "primary", "goal": "complete_execution"},
                    {"branch_id": "fallback", "goal": "safe_partial_completion"},
                ],
                "fallback_paths": [
                    {"step_kind": "plugin_notify", "reason": "act_step_failure"},
                    {"step_kind": "internal_summarize", "reason": "act_step_failure"},
                ],
            },
        }
        out.append(row)
        act_rows.append(row)
        next_order += 1
    primary_act = act_rows[0]
    pp = primary_act.get("payload") if isinstance(primary_act.get("payload"), dict) else {}
    alts = list(pp.get("alternative_paths") or [])
    if len(alts) < 2:
        alts.extend(
            [
                {
                    "step_kind": "plugin_notify",
                    "payload": {
                        "title": "Primary path degraded",
                        "body": "Switching to guarded fallback path A.",
                        "severity": "warning",
                    },
                },
                {
                    "step_kind": "internal_summarize",
                    "payload": {
                        "command": raw,
                        "message": "Fallback path B: summarize and require operator confirmation.",
                    },
                },
            ]
        )
    pp["alternative_paths"] = alts[:4]
    pp["fallback_paths"] = [
        {"path": "fallback_a", "step_kind": "plugin_notify"},
        {"path": "fallback_b", "step_kind": "internal_summarize"},
    ]
    pp["reasoning_stage"] = str(pp.get("reasoning_stage") or "execute")
    primary_act["payload"] = pp
    return sorted(out, key=lambda x: int(x.get("step_order") or 0))


def build_plan_steps_from_command(
    command: str,
    *,
    history_context: dict[str, Any] | None = None,
    execution_context: dict[str, Any] | None = None,
    capability_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Produce ordered steps with phase, step_kind, suggested payload, and risk_level.

    Each step matches the orchestrator contract:
    ``{ step_order, phase, step_kind, risk_level, payload }``.
    """
    raw = str(command or "").strip()
    if not raw:
        return []
    hist = history_context if isinstance(history_context, dict) else {}
    exec_ctx = execution_context if isinstance(execution_context, dict) else {}
    caps = capability_context if isinstance(capability_context, dict) else {}
    cap_map = caps.get("capabilities") if isinstance(caps.get("capabilities"), dict) else {}
    browser_ok = bool((cap_map.get("browser_automation") or {}).get("available", True))
    api_ok = bool((cap_map.get("api_fallback") or {}).get("available", True))
    manual_ok = bool((cap_map.get("manual_assist") or {}).get("available", True))
    hist_attempts = int(hist.get("previous_attempts") or 0)
    hist_outcomes = list(hist.get("previous_outcomes") or [])
    hist_retry_hint = str(hist.get("retry_strategy_hint") or "")
    reasoning = _build_reasoning_depth(raw)

    urls = _urls_in(raw)
    emails = _emails_in(raw)
    steps: list[dict[str, Any]] = []
    order = 0

    def add(phase: str, step_kind: str, risk_level: str, payload: dict[str, Any], *, subtask: str = "") -> None:
        nonlocal order
        order += 1
        steps.append(
            {
                "step_order": order,
                "phase": phase,
                "step_kind": step_kind,
                "risk_level": risk_level,
                "payload": {
                    **payload,
                    "subtask": str(subtask or "")[:240],
                    "validation": _validation_for_step(step_kind),
                },
            }
        )

    # --- search ---
    add(
        "search",
        "internal_context_scan",
        "low",
        {
            "command": raw,
            "urls_hint": urls[:5],
            "emails_hint": emails[:8],
        },
        subtask="Context scan for entities and inputs",
    )

    # --- analyze ---
    add(
        "analyze",
        "internal_command_analysis",
        "low",
        {
            "command": raw,
            "signals": {
                "browser": _wants_browser(raw),
                "email": _wants_email(raw),
                "file": _wants_file(raw),
                "api": _wants_api(raw),
                "notify": _wants_notify(raw),
            },
            "execution_history_context": {
                "previous_attempts": hist_attempts,
                "previous_outcomes": hist_outcomes[:6],
                "retry_strategy_hint": hist_retry_hint,
            },
            "execution_domain_context": {
                "domain": str(exec_ctx.get("domain") or "business"),
                "suppliers_n": len(list(exec_ctx.get("suppliers") or [])),
                "workflows_n": len(list(exec_ctx.get("workflows") or [])),
                "pricing_patterns_n": len(list(exec_ctx.get("pricing_patterns") or [])),
                "risk_models_n": len(list(exec_ctx.get("risk_models") or [])),
            },
            "execution_capabilities": caps,
            "reasoning_depth": reasoning,
        },
        subtask="Intent decomposition and dependency mapping",
    )

    if bool(reasoning.get("multi_step_workflow")):
        add(
            "analyze",
            "internal_workflow_dependency_map",
            "low",
            {
                "sub_goals": list(reasoning.get("sub_goals") or []),
                "dependencies": list(reasoning.get("dependencies") or []),
                "workflow_type": str(reasoning.get("workflow_type") or "multi_step"),
            },
            subtask="Detect multi-step workflow and critical dependencies",
        )

    # --- decide ---
    act_hints: list[str] = []
    if _wants_email(raw):
        act_hints.append("plugin_email")
    if _wants_file(raw):
        act_hints.append("plugin_file")
    if _wants_api(raw):
        act_hints.append("plugin_api")
    if _wants_notify(raw):
        act_hints.append("plugin_notify")
    if _wants_browser(raw):
        act_hints.append("browser")
    if not act_hints:
        act_hints.append("internal_summarize")

    add(
        "decide",
        "internal_execution_branch",
        "low",
        {
            "command": raw,
            "planned_plugins": act_hints,
            "execution_history_context": {
                "previous_attempts": hist_attempts,
                "previous_outcomes": hist_outcomes[:6],
                "retry_strategy_hint": hist_retry_hint,
            },
            "execution_domain_context": {
                "domain": str(exec_ctx.get("domain") or "business"),
                "profile_enabled": bool(exec_ctx.get("profile_enabled", True)),
            },
            "execution_capabilities": caps,
            "reasoning_depth": reasoning,
        },
        subtask="Select execution branch with validation gates",
    )

    # --- act: concrete steps ---
    if _wants_browser(raw) and urls and browser_ok:
        first = urls[0]
        host = (urlparse(first).hostname or first)[:120]
        add("act", "browser_open", "medium", {"url": first, "label": host}, subtask="Open target website")
        if any(k in raw.lower() for k in ("search", "query", "google", "duck")):
            q = raw[:240]
            add("act", "browser_search", "medium", {"query": q, "base_url": first}, subtask="Run target search workflow")
    elif _wants_browser(raw):
        if api_ok and urls:
            add(
                "act",
                "plugin_api",
                "medium",
                {"method": "GET", "url": urls[0], "headers": {}, "json": None, "fallback_reason": "browser_unavailable"},
                subtask="Fallback API fetch because browser automation unavailable",
            )
        elif manual_ok:
            add(
                "act",
                "plugin_notify",
                "low",
                {
                    "title": "Manual assist required",
                    "body": "Browser automation unavailable. Please perform web step manually and confirm outcome.",
                    "severity": "warning",
                },
                subtask="Request manual assist for web workflow",
            )

    if _wants_email(raw):
        add(
            "act",
            "plugin_email",
            "high",
            {
                "to": emails[0] if emails else "",
                "subject": raw[:180],
                "body": raw[:4000],
                "fallback_to_notify": True,
                "notify_title": raw[:180],
                "notify_body": (raw[:500] + " — (email delivery may have failed; in-app copy.)")[:4000],
            },
            subtask="Send communication with fallback notification",
        )

    if _wants_file(raw):
        safe_name = re.sub(r"[^\w.\-]+", "_", raw[:40]).strip("._") or "output"
        add(
            "act",
            "plugin_file",
            "medium",
            {"path": f"vault/actions/{safe_name}.md", "content": f"# Action output\n\n{raw}\n"},
            subtask="Persist execution artifact to file",
        )

    if _wants_api(raw) and api_ok:
        target = _extract_api_target(raw) or ""
        method = "POST" if any(k in raw.lower() for k in ("post", "webhook", "submit")) else "GET"
        risk = "high" if method == "POST" else "medium"
        add(
            "act",
            "plugin_api",
            risk,
            {
                "method": method,
                "url": target,
                "json": None,
                "headers": {},
            },
            subtask="Execute API call with response validation",
        )
    elif _wants_api(raw) and manual_ok:
        add(
            "act",
            "plugin_notify",
            "low",
            {
                "title": "Manual API assist",
                "body": "API connector unavailable. Please run this API step manually and provide the response.",
                "severity": "warning",
            },
            subtask="Request manual assist for API step",
        )

    if _wants_notify(raw):
        add(
            "act",
            "plugin_notify",
            "low",
            {"title": "Thiramai action", "body": raw[:500], "severity": "info"},
            subtask="Notify user of workflow result",
        )

    if act_hints == ["internal_summarize"] or not any(s["phase"] == "act" for s in steps):
        add(
            "act",
            "internal_summarize",
            "low",
            {"command": raw, "message": "No external act matched; returning structured summary only."},
            subtask="Summarize execution plan and outcomes",
        )
    steps = _ensure_deep_planning_contract(raw=raw, steps=steps, reasoning=reasoning)
    conf = _plan_confidence(raw, steps, reasoning)
    for s in steps:
        p = s.get("payload") if isinstance(s.get("payload"), dict) else {}
        s["payload"] = {
            **p,
            "plan_confidence_score": conf,
            "reasoning_depth": reasoning,
            "reasoning_stage": str(
                p.get("reasoning_stage")
                or ("research" if str(s.get("phase") or "") == "search" else ("decide" if str(s.get("phase") or "") == "decide" else ("execute" if str(s.get("phase") or "") == "act" else "analyze")))
            ),
            "structured_plan": {
                "phase": str(s.get("phase") or ""),
                "subtask": str((p.get("subtask") if isinstance(p, dict) else "") or ""),
                "validation": dict((p.get("validation") if isinstance(p, dict) else {}) or {}),
            },
        }
    return steps
