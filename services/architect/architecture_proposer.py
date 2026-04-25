"""Self-Architecture Modification — Self-Evolution Phase 4 Task 1.

The system can propose its OWN new service modules. Lifecycle:

1. ``detect_capability_gaps`` (or an explicit ``propose_module``) emits a
   needed-capability description.
2. ``propose_module`` calls Groq to design a new service module — both the
   implementation and a smoke test — and persists an
   :class:`~core.db.models.ArchitectureProposal` row with status ``proposed``.
3. ``sandbox_proposal`` writes the candidate as a unified diff for the
   existing :mod:`services.sandbox_service` and runs pytest *inside* the
   sandbox container. Status becomes ``sandboxed`` (passed/failed).
4. ``approve_proposal`` is owner-only. On approval **and** sandbox-passed, the
   file is materialised at ``proposed_path`` (under ``services/dynamic/``) and
   an :class:`~core.db.models.EvolutionTrigger` is opened so the standard
   self-coder pipeline can pick the change up. CI/CD then deploys via the
   normal `git push` → GitHub Actions path.
5. Rejection records the reason for audit.

Hard safety: nothing in this module imports the generated code in-process. The
sandbox is the only place generated code is executed before owner approval.

Environment toggles:

- ``THIRAMAI_ARCHITECT_AUTO_PROPOSE=1`` enable the hourly auto-proposal loop
  (off by default; the founder must opt in)
- ``THIRAMAI_ARCHITECT_MAX_OPEN_PROPOSALS`` cap on open proposals (default 3)
- ``GROQ_API_KEY`` required for LLM design steps
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select

from core.db.models import (
    ArchitectureProposal,
    EvolutionTrigger,
    LearningLog,
)

_LOG = logging.getLogger(__name__)

_AUTO_FLAG = "THIRAMAI_ARCHITECT_AUTO_PROPOSE"
_MAX_OPEN_KEY = "THIRAMAI_ARCHITECT_MAX_OPEN_PROPOSALS"
_DEFAULT_MAX_OPEN = 3
_DEFAULT_DYNAMIC_DIR = "services/dynamic"

# Names / paths the LLM is forbidden from touching, to keep blast radius
# bounded even if a sandbox check is somehow bypassed.
_FORBIDDEN_PATH_TOKENS = (
    "..",
    "alembic/",
    "alembic\\",
    "core/auth",
    "core/security",
    "core/db/models",
    "core/database",
    "core/middleware",
    "core/dangerous",
    "core/rate_limit",
    "settings.py",
    "app.py",
)

_PY_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factory_or_none():
    try:
        from core.database import get_session_factory

        return get_session_factory()
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _max_open_proposals() -> int:
    raw = (os.getenv(_MAX_OPEN_KEY) or "").strip()
    if not raw:
        return _DEFAULT_MAX_OPEN
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_OPEN


def _auto_propose_enabled() -> bool:
    return (os.getenv(_AUTO_FLAG) or "").strip().lower() in ("1", "true", "yes", "on")


def _safe_module_name(name: str) -> str | None:
    candidate = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    candidate = re.sub(r"[^a-z0-9_]", "", candidate)
    if not _PY_NAME_RE.match(candidate):
        return None
    return candidate


def _proposed_path_for(name: str) -> str:
    return f"{_DEFAULT_DYNAMIC_DIR}/{name}.py"


def _path_is_safe(path: str) -> tuple[bool, str]:
    norm = path.replace("\\", "/").lower()
    if not norm.startswith(f"{_DEFAULT_DYNAMIC_DIR}/"):
        return False, f"path must start with {_DEFAULT_DYNAMIC_DIR}/"
    for tok in _FORBIDDEN_PATH_TOKENS:
        if tok in norm:
            return False, f"path contains forbidden token: {tok!r}"
    if not norm.endswith(".py"):
        return False, "path must end with .py"
    return True, "ok"


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _split_design_blocks(text: str) -> dict[str, str]:
    """Parse the LLM design response into ``summary``, ``code``, ``tests``.

    Expected format (loose; tolerant of missing sections):

    ``# SUMMARY``     ... ``# CODE`` ... ``# TESTS`` ...
    """
    if not text:
        return {"summary": "", "code": "", "tests": ""}
    pattern = re.compile(
        r"#\s*(SUMMARY|CODE|TESTS)\s*\n",
        re.IGNORECASE,
    )
    parts: dict[str, str] = {"summary": "", "code": "", "tests": ""}
    matches = list(pattern.finditer(text))
    if not matches:
        # Treat the whole blob as code; we can still sandbox it.
        parts["code"] = _strip_fences(text)
        return parts
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts[key] = _strip_fences(text[start:end])
    return parts


def _looks_like_python(code: str) -> bool:
    if not code or len(code) < 20:
        return False
    head = code.lstrip().splitlines()[:30]
    joined = "\n".join(head)
    if "import " not in joined and "def " not in joined and "class " not in joined:
        return False
    if "subprocess" in code and "shell=True" in code:
        # Disallow shell=True in generated code by default.
        return False
    return True


def _diff_from_new_file(path: str, code: str) -> str:
    """Return a unified diff that creates ``path`` with ``code`` (no trailing newline normalisation)."""
    body = code.rstrip("\n") + "\n"
    lines = body.splitlines(keepends=False)
    header = (
        f"diff --git a/{path} b/{path}\n"
        f"new file mode 100644\n"
        f"--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
    )
    diff_body = "\n".join("+" + ln for ln in lines)
    return header + diff_body + "\n"


# ---------------------------------------------------------------------------
# LLM design step
# ---------------------------------------------------------------------------


def _design_with_groq(
    *,
    name: str,
    need_description: str,
    inspiration_paths: Iterable[str] = (),
) -> tuple[bool, dict[str, str], str]:
    """Ask Groq to design ``services/dynamic/<name>.py`` plus a smoke test.

    Returns ``(ok, blocks, model_note)``.
    """
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return False, {}, "GROQ_API_KEY missing"
    try:
        from groq import Groq  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover — missing optional dep
        return False, {}, f"groq sdk unavailable: {exc}"

    sys_prompt = (
        "You are a senior Python service architect for the Thiramai Sovereign OS. "
        "Design ONE new self-contained service module that fulfils the requested capability. "
        "Hard rules:\n"
        "  1. The module must live at services/dynamic/<name>.py — NO other path is allowed.\n"
        "  2. NO database schema changes. NO new third-party dependencies. Stdlib only "
        "     unless you can clearly see the dep already in requirements (groq, sqlalchemy, "
        "     httpx, joblib, scikit-learn, lightgbm, redis are OK).\n"
        "  3. NO subprocess.* with shell=True. NO os.system. NO exec/eval.\n"
        "  4. Provide pure functions where possible; one optional class is fine. "
        "     Do not start background threads at import time.\n"
        "  5. Output MUST contain three sections, each headed by exactly:\n"
        "        # SUMMARY\n"
        "        # CODE\n"
        "        # TESTS\n"
        "     SUMMARY: 4-8 plain English sentences describing the module.\n"
        "     CODE: complete Python source for services/dynamic/<name>.py.\n"
        "     TESTS: a pytest file (no fixtures) that imports the module and exercises "
        "     the happy path. Keep tests fast (<2s) and offline.\n"
        "  6. Do NOT add markdown fences inside the SUMMARY / CODE / TESTS blocks."
    )

    inspirations = ""
    for rel in list(inspiration_paths)[:3]:
        try:
            text = Path(rel).read_text(encoding="utf-8", errors="replace")[:3000]
            inspirations += f"\n### Inspiration {rel}\n```python\n{text}\n```\n"
        except OSError:
            continue

    user_prompt = (
        f"Module name: {name}\n"
        f"Path: services/dynamic/{name}.py\n\n"
        f"Capability needed:\n{need_description.strip()}\n"
        f"{inspirations}"
    )

    client = Groq(api_key=key)
    model = (os.getenv("THIRAMAI_ARCHITECT_MODEL") or "llama-3.3-70b-versatile").strip()
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt[:80_000]},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    raw = completion.choices[0].message.content or ""
    blocks = _split_design_blocks(raw)
    if not _looks_like_python(blocks.get("code") or ""):
        return False, blocks, f"model={model} did not return runnable Python"
    return True, blocks, f"model={model}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_proposals_count() -> int:
    factory = _factory_or_none()
    if factory is None:
        return 0
    with factory() as session:
        try:
            row = (
                session.execute(
                    select(func.count(ArchitectureProposal.id)).where(
                        ArchitectureProposal.status.in_(("proposed", "sandboxed"))
                    )
                )
                .scalars()
                .first()
            )
            return int(row or 0)
        except Exception:
            return 0


def list_proposals(*, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    factory = _factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        try:
            stmt = select(ArchitectureProposal).order_by(ArchitectureProposal.id.desc()).limit(limit)
            if status:
                stmt = stmt.where(ArchitectureProposal.status == status)
            rows = session.execute(stmt).scalars().all()
        except Exception:
            return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r.id),
                "name": r.name,
                "status": r.status,
                "proposed_path": r.proposed_path,
                "sandbox_passed": bool(r.sandbox_passed),
                "sandbox_exit_code": r.sandbox_exit_code,
                "model_note": r.model_note,
                "approved_by": r.approved_by,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                "rejected_reason": r.rejected_reason,
                "need_description": (r.need_description or "")[:240],
                "module_summary": (r.module_summary or "")[:480],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def propose_module(
    *,
    name: str,
    need_description: str,
    organization_id: int | None = None,
    proposed_by_user_id: int | None = None,
    inspiration_paths: Iterable[str] = (),
) -> dict[str, Any]:
    """Generate and persist a new architecture proposal.

    Does NOT execute generated code. Use :func:`sandbox_proposal` next.
    """
    safe = _safe_module_name(name)
    if not safe:
        return {"ok": False, "stage": "validate", "error": "name_invalid"}

    if open_proposals_count() >= _max_open_proposals():
        return {
            "ok": False,
            "stage": "throttle",
            "error": "too_many_open_proposals",
            "limit": _max_open_proposals(),
        }

    target_path = _proposed_path_for(safe)
    path_ok, path_reason = _path_is_safe(target_path)
    if not path_ok:
        return {"ok": False, "stage": "validate", "error": path_reason}

    ok, blocks, model_note = _design_with_groq(
        name=safe,
        need_description=need_description,
        inspiration_paths=inspiration_paths,
    )
    if not ok:
        return {"ok": False, "stage": "design", "error": model_note, "preview": blocks}

    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "stage": "persist", "error": "no_db"}

    with factory() as session:
        row = ArchitectureProposal(
            organization_id=organization_id,
            proposed_by_user_id=proposed_by_user_id,
            name=safe[:128],
            need_description=str(need_description or "")[:4_000],
            module_summary=str(blocks.get("summary") or "")[:4_000],
            proposed_path=target_path[:255],
            generated_code=str(blocks.get("code") or "")[:60_000],
            generated_tests=str(blocks.get("tests") or "")[:30_000],
            status="proposed",
            model_note=model_note[:255],
            evidence={
                "inspiration_paths": list(inspiration_paths)[:8],
                "designed_at": _now().isoformat(),
            },
        )
        session.add(row)
        session.commit()
        proposal_id = int(row.id)

    _LOG.info(
        "architect.proposed id=%s name=%s path=%s note=%s",
        proposal_id,
        safe,
        target_path,
        model_note[:80],
    )
    return {
        "ok": True,
        "stage": "proposed",
        "id": proposal_id,
        "name": safe,
        "path": target_path,
        "model_note": model_note,
    }


def sandbox_proposal(proposal_id: int) -> dict[str, Any]:
    """Apply the proposal as a candidate diff and run pytest inside the sandbox.

    Updates the row in-place; returns the verdict.
    """
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "stage": "persist", "error": "no_db"}

    from services import sandbox_service

    if not sandbox_service.sandbox_enabled():
        return {
            "ok": False,
            "stage": "sandbox_flag",
            "error": "THIRAMAI_KERNEL_SANDBOX disabled",
        }

    with factory() as session:
        row = session.get(ArchitectureProposal, int(proposal_id))
        if row is None:
            return {"ok": False, "stage": "lookup", "error": "not_found"}
        if row.status not in ("proposed", "sandboxed"):
            return {
                "ok": False,
                "stage": "state",
                "error": f"cannot sandbox a proposal in status {row.status!r}",
            }

        path_ok, path_reason = _path_is_safe(row.proposed_path)
        if not path_ok:
            row.status = "rejected"
            row.rejected_reason = f"path_check: {path_reason}"
            row.updated_at = _now()
            session.commit()
            return {"ok": False, "stage": "path", "error": path_reason}

        if not _looks_like_python(row.generated_code):
            row.status = "rejected"
            row.rejected_reason = "generated_code_not_python"
            row.updated_at = _now()
            session.commit()
            return {"ok": False, "stage": "code", "error": "not_python"}

        diff = _diff_from_new_file(row.proposed_path, row.generated_code)
        try:
            sandbox_service.candidate_patch_path().parent.mkdir(parents=True, exist_ok=True)
            from core.security.sandbox_policy import enforce_llm_write_path

            target = enforce_llm_write_path(
                sandbox_service.candidate_patch_path(),
                operation="architect_patch_write",
            )
            target.write_text(diff, encoding="utf-8")
        except Exception as exc:
            row.status = "rejected"
            row.rejected_reason = f"diff_write_failed: {exc}"
            row.updated_at = _now()
            session.commit()
            return {"ok": False, "stage": "write", "error": str(exc)}

        # We use the project's smoke + production safety tests as the gate.
        # The new module itself is executed at import time inside the sandbox
        # only if a test imports it; otherwise it merely sits on disk.
        targets = (
            os.getenv("THIRAMAI_ARCHITECT_PYTEST_TARGETS")
            or "tests/test_smoke.py tests/test_production_safety.py"
        )
        started = time.monotonic()
        code, log_text = sandbox_service.run_pytest_in_sandbox(pytest_targets=targets)
        elapsed = time.monotonic() - started

        row.sandbox_exit_code = int(code)
        row.sandbox_log = (log_text or "")[-12_000:]
        row.sandbox_passed = bool(code == 0)
        row.status = "sandboxed"
        row.evidence = dict(row.evidence or {})
        row.evidence["sandbox_seconds"] = round(elapsed, 2)
        row.evidence["sandboxed_at"] = _now().isoformat()
        row.updated_at = _now()
        session.commit()
        verdict = {
            "ok": row.sandbox_passed,
            "stage": "sandboxed",
            "id": int(row.id),
            "passed": row.sandbox_passed,
            "exit_code": row.sandbox_exit_code,
            "seconds": round(elapsed, 2),
            "log_tail": (row.sandbox_log or "")[-2000:],
        }

    _LOG.info(
        "architect.sandboxed id=%s passed=%s code=%s seconds=%.2f",
        verdict["id"],
        verdict["passed"],
        verdict["exit_code"],
        verdict["seconds"],
    )
    return verdict


def approve_proposal(
    *,
    proposal_id: int,
    approver_user_id: int,
    approved: bool = True,
    rejected_reason: str = "",
) -> dict[str, Any]:
    """Owner-only approval (caller must enforce RBAC).

    On approval **and** sandbox-passed, the file is materialised on disk under
    ``services/dynamic/`` and a matching :class:`EvolutionTrigger` is opened
    for downstream pipelines (CI/CD picks the file up on the next deploy).
    """
    factory = _factory_or_none()
    if factory is None:
        return {"ok": False, "stage": "persist", "error": "no_db"}

    with factory() as session:
        row = session.get(ArchitectureProposal, int(proposal_id))
        if row is None:
            return {"ok": False, "stage": "lookup", "error": "not_found"}

        if not approved:
            row.status = "rejected"
            row.rejected_reason = (rejected_reason or "rejected by owner")[:4000]
            row.approved_by = int(approver_user_id)
            row.approved_at = _now()
            row.updated_at = _now()
            session.commit()
            return {"ok": True, "stage": "rejected", "id": int(row.id)}

        if not row.sandbox_passed:
            return {
                "ok": False,
                "stage": "sandbox",
                "error": "sandbox_not_passed",
                "exit_code": row.sandbox_exit_code,
            }

        path_ok, path_reason = _path_is_safe(row.proposed_path)
        if not path_ok:
            row.status = "rejected"
            row.rejected_reason = f"path_check: {path_reason}"
            row.approved_by = int(approver_user_id)
            row.approved_at = _now()
            row.updated_at = _now()
            session.commit()
            return {"ok": False, "stage": "path", "error": path_reason}

        repo_root = Path(__file__).resolve().parents[2]
        target = repo_root / row.proposed_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Ensure services/dynamic is a real package (idempotent).
        pkg_init = target.parent / "__init__.py"
        if not pkg_init.is_file():
            pkg_init.write_text(
                '"""Auto-managed package for owner-approved Phase 4 modules."""\n',
                encoding="utf-8",
            )
        if target.exists():
            return {
                "ok": False,
                "stage": "deploy",
                "error": "target_exists",
                "path": str(row.proposed_path),
            }
        target.write_text(row.generated_code, encoding="utf-8")

        row.status = "deployed"
        row.approved_by = int(approver_user_id)
        row.approved_at = _now()
        row.updated_at = _now()

        trig = EvolutionTrigger(
            trigger_type="architecture_proposal",
            target=row.proposed_path,
            reason=f"Owner-approved Phase 4 module {row.name!r}.",
            proposed_change=row.module_summary[:4000] or "Owner-approved new module deployed.",
            status="applied",
            evidence={
                "architecture_proposal_id": int(row.id),
                "sandbox_exit_code": row.sandbox_exit_code,
                "approved_by": int(approver_user_id),
            },
        )
        session.add(trig)
        session.commit()

        return {
            "ok": True,
            "stage": "deployed",
            "id": int(row.id),
            "path": row.proposed_path,
            "trigger_id": int(trig.id),
        }


# ---------------------------------------------------------------------------
# Capability gap detection (lightweight heuristic)
# ---------------------------------------------------------------------------


_CAPABILITY_HINT_RE = re.compile(
    r"\b(?:we need|missing|capability|feature|module)\b\s*[:\-]?\s*(.{6,160})",
    re.IGNORECASE,
)


def detect_capability_gaps(*, lookback_days: int = 7, limit: int = 5) -> list[dict[str, Any]]:
    """Mine recent ``LearningLog`` lessons for ``"we need X capability"``-style hints.

    This is intentionally conservative: it returns at most ``limit`` hints and
    de-duplicates on a normalised key. The auto-propose loop applies cooldowns
    on top of this.
    """
    factory = _factory_or_none()
    if factory is None:
        return []
    cutoff = _now() - timedelta(days=int(lookback_days))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    try:
        with factory() as session:
            stmt = (
                select(LearningLog)
                .where(LearningLog.created_at >= cutoff)
                .order_by(LearningLog.id.desc())
                .limit(400)
            )
            rows = session.execute(stmt).scalars().all()
    except Exception:
        return []

    for r in rows:
        text_blob = " ".join(
            str(v or "")
            for v in (
                r.lesson_summary,
                r.action_type,
                (r.context or {}).get("note") if isinstance(r.context, dict) else "",
            )
        )
        m = _CAPABILITY_HINT_RE.search(text_blob)
        if not m:
            continue
        snippet = m.group(1).strip().rstrip(".!?,;:").lower()
        key = re.sub(r"[^a-z0-9 ]+", "", snippet)[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        # Derive a candidate module name (snake_case from first 3 alpha tokens).
        tokens = [t for t in re.findall(r"[a-z]+", key) if len(t) > 2]
        if not tokens:
            continue
        candidate = "_".join(tokens[:3])
        if not _safe_module_name(candidate):
            continue
        out.append(
            {
                "name": candidate,
                "need_description": snippet,
                "evidence_log_id": int(r.id),
            }
        )
        if len(out) >= int(limit):
            break
    return out


def auto_propose_loop() -> dict[str, Any]:
    """Hourly entry point. Off unless ``THIRAMAI_ARCHITECT_AUTO_PROPOSE=1``.

    Always returns a small status payload (never raises) so the scheduler can
    log it cleanly.
    """
    if not _auto_propose_enabled():
        return {"ok": True, "skipped": True, "reason": "auto_propose_disabled"}
    open_count = open_proposals_count()
    cap = _max_open_proposals()
    if open_count >= cap:
        return {"ok": True, "skipped": True, "reason": "open_proposal_cap", "open": open_count}

    gaps = detect_capability_gaps()
    if not gaps:
        return {"ok": True, "skipped": True, "reason": "no_gaps"}

    proposed: list[dict[str, Any]] = []
    for gap in gaps[: max(1, cap - open_count)]:
        try:
            res = propose_module(
                name=gap["name"],
                need_description=gap["need_description"],
            )
        except Exception as exc:  # pragma: no cover — defensive
            _LOG.warning("architect.auto_propose failure: %s", exc)
            continue
        proposed.append({"name": gap["name"], "result": res.get("stage", "unknown")})
    return {"ok": True, "skipped": False, "proposed": proposed}


def get_status() -> dict[str, Any]:
    """Capability snapshot for ``GET /personal/os/brain-health``."""
    factory = _factory_or_none()
    counts: dict[str, int] = {"proposed": 0, "sandboxed": 0, "approved": 0, "deployed": 0, "rejected": 0}
    last_deployed_at: str | None = None
    if factory is not None:
        try:
            with factory() as session:
                stmt = select(ArchitectureProposal.status, func.count()).group_by(
                    ArchitectureProposal.status
                )
                for status, n in session.execute(stmt).all():
                    counts[str(status)] = int(n)
                last = (
                    session.execute(
                        select(ArchitectureProposal.approved_at)
                        .where(ArchitectureProposal.status == "deployed")
                        .order_by(ArchitectureProposal.approved_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                if last is not None:
                    last_deployed_at = last.isoformat()
        except Exception:
            pass
    return {
        "auto_propose_enabled": _auto_propose_enabled(),
        "open_proposals": int(counts.get("proposed", 0) + counts.get("sandboxed", 0)),
        "max_open_proposals": _max_open_proposals(),
        "groq_available": bool((os.getenv("GROQ_API_KEY") or "").strip()),
        "counts": counts,
        "last_deployed_at": last_deployed_at,
    }


__all__ = [
    "approve_proposal",
    "auto_propose_loop",
    "detect_capability_gaps",
    "get_status",
    "list_proposals",
    "open_proposals_count",
    "propose_module",
    "sandbox_proposal",
]
