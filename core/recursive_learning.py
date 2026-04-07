"""
Post-mortem + safe append-only updates to `prompts_v2.md` (recursive self-correction skeleton).

Persists HITL outcomes and execution results to PostgreSQL ``learning_logs`` (org-scoped) so the
context engine can surface past lessons in council prompts. Does not paste raw user text into
policies — only sanitized error-class summaries.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select

from core.database import get_session_factory
from core.db.models import LearningLog
from core.observability import log_action_engine, log_event

_POLICIES = Path(__file__).resolve().parent / "policies"
V2_PATH = _POLICIES / "prompts_v2.md"
_LEARNING_LOG = Path(__file__).resolve().parents[1] / "vault" / "recursive_learning.jsonl"

_MAX_APPEND_LINE = 280
_MAX_V2_TAIL_LINES = 120


def _sanitize_lesson(text: str) -> str:
    t = re.sub(r"[^\w\s.,;:%/-]", "", (text or "")[:400])
    t = " ".join(t.split())
    return t[:_MAX_APPEND_LINE]


def _compact_value(val: Any, max_str: int = 96, depth: int = 0) -> Any:
    if depth > 4:
        return "…"
    if val is None or isinstance(val, (bool, int, float)):
        return val
    if isinstance(val, str):
        s = val.strip().replace("\n", " ")
        return s if len(s) <= max_str else s[: max_str - 1] + "…"
    if isinstance(val, dict):
        return {str(k)[:64]: _compact_value(v, max_str, depth + 1) for k, v in list(val.items())[:24]}
    if isinstance(val, (list, tuple)):
        return [_compact_value(x, max_str, depth + 1) for x in list(val)[:24]]
    return str(val)[:max_str]


def compact_payload_for_learning(payload: Any) -> Any:
    """Shrink approval/job payloads for ``learning_logs.context`` (no full PII dumps)."""
    if not isinstance(payload, dict):
        return {}
    return _compact_value(dict(payload))


def context_from_approval_row(row: dict[str, Any]) -> dict[str, Any]:
    """Structured context from a pending-approval / resolve row dict."""
    pl = row.get("payload")
    return {
        "approval_id": row.get("id"),
        "summary": (row.get("summary") or "")[:800],
        "risk_tier": row.get("risk_tier"),
        "payload_outline": compact_payload_for_learning(pl if isinstance(pl, dict) else {}),
    }


def _build_lesson_summary(
    *,
    outcome: str,
    action_type: str,
    user_feedback: str,
    result: dict[str, Any],
) -> str:
    fb = _sanitize_lesson(user_feedback)[:220] if user_feedback else ""
    err = ""
    if isinstance(result, dict):
        if result.get("error"):
            err = _sanitize_lesson(str(result["error"]))[:160]
        elif not result.get("ok", True) and result.get("message"):
            err = _sanitize_lesson(str(result["message"]))[:120]
    core = f"{outcome} · {action_type or 'unknown'}"
    if fb:
        core += f" · note: {fb}"
    elif err:
        core += f" · {err}"
    return core[:900]


def _json_safe_dict(d: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(d, default=str))
    except (TypeError, ValueError):
        return {"serialization": "fallback", "preview": str(d)[:800]}


def record_learning_log(
    *,
    organization_id: int,
    outcome: str,
    action_type: str,
    context: dict[str, Any],
    result: dict[str, Any],
    user_feedback: str = "",
    approval_id: str | None = None,
    resolved_by_user_id: int | None = None,
) -> int | None:
    """
    Insert one org-scoped learning row. No-op if DATABASE_URL is unset.

    ``outcome``: ``rejected`` | ``executed`` | ``execution_failed`` | ``duplicate_skip``.
    """
    factory = get_session_factory()
    if factory is None:
        return None
    aid: uuid.UUID | None = None
    if approval_id:
        try:
            aid = uuid.UUID(str(approval_id).strip())
        except ValueError:
            aid = None
    ctx_j = _json_safe_dict(dict(context or {}))
    res_in = dict(result or {}) if isinstance(result, dict) else {"raw": str(result)[:500]}
    res_j = _json_safe_dict(res_in)
    summary = _build_lesson_summary(
        outcome=outcome,
        action_type=action_type,
        user_feedback=user_feedback,
        result=res_j,
    )
    row = LearningLog(
        organization_id=int(organization_id),
        approval_id=aid,
        outcome=outcome[:32],
        action_type=(action_type or "")[:128],
        lesson_summary=summary,
        context=ctx_j,
        result=res_j,
        user_feedback=(user_feedback or "").strip()[:4000] or None,
        resolved_by_user_id=int(resolved_by_user_id) if resolved_by_user_id and resolved_by_user_id > 0 else None,
    )
    with factory() as session:
        with session.begin():
            session.add(row)
            session.flush()
            return int(row.id)


def _fetch_recent_logs(*, organization_id: int, limit: int = 40) -> list[dict[str, Any]]:
    factory = get_session_factory()
    if factory is None:
        return []
    oid = int(organization_id)
    with factory() as session:
        stmt = (
            select(LearningLog)
            .where(LearningLog.organization_id == oid)
            .order_by(desc(LearningLog.created_at))
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "outcome": r.outcome,
                    "action_type": r.action_type,
                    "lesson_summary": r.lesson_summary,
                    "user_feedback": (r.user_feedback or "")[:400],
                    "context": r.context if isinstance(r.context, dict) else {},
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
            )
        return out


def _query_tokens(user_query: str) -> list[str]:
    raw = re.findall(r"\w{4,}", (user_query or "").lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in raw[:16]:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def lessons_prompt_block(
    user_query: str,
    *,
    organization_id: int,
    max_chars: int = 1000,
    max_bullets: int = 8,
) -> str:
    """
    Rank recent ``learning_logs`` by token overlap with ``user_query``, then trim to ``max_chars``.
    Injected into council context (see ``context_engine.load_vault_context``).
    """
    logs = _fetch_recent_logs(organization_id=int(organization_id), limit=45)
    if not logs:
        return ""
    tokens = _query_tokens(user_query)

    def _score(entry: dict[str, Any]) -> int:
        if not tokens:
            return 0
        blob = json.dumps(
            {
                "s": entry.get("lesson_summary"),
                "c": entry.get("context"),
                "f": entry.get("user_feedback"),
            },
            ensure_ascii=False,
        ).lower()
        return sum(1 for t in tokens if t in blob)

    if tokens:
        # ``logs`` is newest-first; for equal relevance scores prefer newer rows (lower index).
        ranked = [pair[1] for pair in sorted(enumerate(logs), key=lambda p: (-_score(p[1]), p[0]))]
    else:
        ranked = logs

    lines: list[str] = ["## Past business lessons (HITL post-mortems — do not repeat the same mistakes)"]
    used = len(lines[0]) + 2
    for entry in ranked[: max_bullets * 2]:
        oc = entry.get("outcome") or "?"
        at = entry.get("action_type") or ""
        ls = (entry.get("lesson_summary") or "")[:320]
        line = f"- **[{oc}]** `{at}` — {ls}"
        if used + len(line) + 2 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
        if len(lines) - 1 >= max_bullets:
            break
    if len(lines) <= 1:
        return ""
    return "\n".join(lines).strip()


def post_mortem_analysis_text(
    *,
    ok: bool,
    route_tag: str,
    error: BaseException | None,
    outcome_preview: str,
    user_message_snippet: str,
) -> str:
    """Structured one-paragraph post-mortem for logs (not necessarily written to prompts)."""
    if ok:
        return (
            f"POST_MORTEM ok route={route_tag} out_chars={len(outcome_preview)} "
            f"user_snip={_sanitize_lesson(user_message_snippet)[:80]}"
        )
    en = type(error).__name__ if error else "Unknown"
    em = _sanitize_lesson(str(error) if error else "")[:120]
    return f"POST_MORTEM FAIL route={route_tag} err={en} msg={em}"


def _append_auto_learned_line(line: str) -> None:
    """Append under ## AUTO_LEARNED_NOTES in prompts_v2.md (cap file tail)."""
    line = line.strip()
    if not line:
        return
    _POLICIES.mkdir(parents=True, exist_ok=True)
    if not V2_PATH.is_file():
        V2_PATH.write_text(
            "# THIRAMAI prompts v2 (recursive learning)\n\n"
            "## AUTO_LEARNED_NOTES\n"
            "_System-appended constraints from post-mortem failures — short lines only._\n\n",
            encoding="utf-8",
        )
    raw = V2_PATH.read_text(encoding="utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    entry = f"- [{ts}] {line}\n"
    new_body = raw.rstrip() + "\n" + entry
    lines = new_body.splitlines()
    if len(lines) > _MAX_V2_TAIL_LINES + 80:
        # keep header + last N lines
        head = lines[:8]
        tail = lines[-_MAX_V2_TAIL_LINES:]
        new_body = "\n".join(head + ["", "... [truncated older AUTO_LEARNED_NOTES] ...", ""] + tail) + "\n"
    V2_PATH.write_text(new_body, encoding="utf-8")


def _append_jsonl(record: dict[str, Any]) -> None:
    _LEARNING_LOG.parent.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts_utc", datetime.now(timezone.utc).isoformat())
    with _LEARNING_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_post_mortem(
    *,
    request_id: str,
    route_tag: str,
    outcome_text: str,
    error: BaseException | None,
    user_message: str,
    latency_ms: float,
    organization_id: int | None = None,
) -> None:
    """
    After each brain run: log post-mortem. On hard failures, append a v2 policy line + jsonl audit.
    """
    partial = (outcome_text or "").strip().startswith("**Partial response:**")
    ok = error is None and bool((outcome_text or "").strip()) and not partial
    snippet = (user_message or "")[:400]
    pm = post_mortem_analysis_text(
        ok=ok,
        route_tag=route_tag,
        error=error,
        outcome_preview=outcome_text or "",
        user_message_snippet=snippet,
    )
    extra_pm: dict[str, Any] = {"route": route_tag, "summary": pm[:500]}
    if organization_id is not None:
        extra_pm["organization_id"] = int(organization_id)
    log_event(
        request_id,
        "orchestrator.post_mortem",
        ok=ok,
        latency_ms=latency_ms,
        extra=extra_pm,
    )
    ae_extra: dict[str, Any] = {"route": route_tag, "partial": partial}
    if organization_id is not None:
        ae_extra["organization_id"] = int(organization_id)
    log_action_engine(
        request_id,
        "recursive_learning.post_mortem",
        action_type="brain_run",
        risk_tier="low",
        ok=ok,
        extra=ae_extra,
    )
    jl: dict[str, Any] = {
        "request_id": request_id,
        "route": route_tag,
        "ok": ok,
        "partial": partial,
        "error_type": type(error).__name__ if error else None,
        "latency_ms": latency_ms,
        "post_mortem": pm,
    }
    if organization_id is not None:
        jl["organization_id"] = int(organization_id)
    _append_jsonl(jl)
    if error is not None or partial:
        try:
            from services.thought_stream import append_exception_thought, append_thought

            if error is not None:
                append_exception_thought(
                    error,
                    prefix=f"Brain post-mortem route={route_tag} request_id={request_id}",
                    phase="post_mortem",
                    agent="recursive_learning",
                    request_id=request_id,
                    with_traceback=False,
                )
            elif partial:
                append_thought(
                    f"Brain post-mortem partial/degraded council route={route_tag} request_id={request_id}",
                    phase="post_mortem",
                    agent="recursive_learning",
                    request_id=request_id,
                )
        except Exception:
            pass
        lesson = _sanitize_lesson(
            f"Avoid repeat: route={route_tag} err={type(error).__name__ if error else 'partial'} "
            f"{(str(error) if error else 'council_degraded')[:100]}"
        )
        _append_auto_learned_line(lesson)


def get_auto_learned_context(max_chars: int = 1200) -> str:
    """Optional: inject into council pack (trimmed AUTO_LEARNED_NOTES from v2)."""
    if not V2_PATH.is_file():
        return ""
    text = V2_PATH.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^## AUTO_LEARNED_NOTES\s*\n(.*)$", text)
    if not m:
        return ""
    block = m.group(1).strip()
    if len(block) > max_chars:
        block = block[-max_chars:] + "\n[...trimmed...]"
    return f"## Recursive learning (prompts_v2)\n{block}"
