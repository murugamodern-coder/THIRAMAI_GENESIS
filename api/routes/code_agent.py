"""
Thiramai Code Agent — Groq-backed generation, syntax check, isolated test, optional git deploy.

Temp workspace: ``{tempdir}/thiramai_agent/{task_id}/``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from core.database import get_session_factory
from services.membership_service import list_memberships_for_user
from services.website_db_service import get_generated_website_sync

_log = logging.getLogger("thiramai.code_agent")

REPO_ROOT = Path(__file__).resolve().parents[2]

router = APIRouter(tags=["Code Agent"])
websites_router = APIRouter(tags=["Code Agent — Websites"])

_MODEL = (os.getenv("THIRAMAI_CODE_AGENT_MODEL") or "llama-3.3-70b-versatile").strip()
_DEPLOY_TOKEN = (os.getenv("THIRAMAI_CODE_AGENT_DEPLOY_TOKEN") or "").strip()

# task_id -> record
_TASKS: dict[str, dict[str, Any]] = {}
_TASK_ORDER: list[str] = []


def _agent_base_dir() -> Path:
    base = Path(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp") / "thiramai_agent"
    return base


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _language_filename(language: str) -> tuple[str, str]:
    lang = (language or "python").strip().lower()
    if lang in ("python", "py"):
        return "generated.py", "python"
    if lang in ("javascript", "js"):
        return "generated.js", "javascript"
    if lang in ("typescript", "ts"):
        return "generated.ts", "typescript"
    if lang in ("react", "jsx"):
        return "Generated.jsx", "react"
    return "generated.py", "python"


def _groq_generate_code(*, task: str, language: str, context: str) -> str:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not configured")

    from groq import Groq

    sys_msg = (
        "You are an expert Python/React developer.\n"
        "Generate production-ready code.\n"
        "Always include error handling.\n"
        "Return ONLY code, no explanation."
    )
    user_msg = (
        f"Task: {task}\n"
        f"Language/framework: {language}\n"
        f"Context: {context}\n"
    )
    client = Groq(api_key=key)
    completion = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg[:48_000]},
        ],
        temperature=0.2,
        max_tokens=8192,
    )
    raw = completion.choices[0].message.content or ""
    return _strip_code_fences(raw)


def _syntax_check(path: Path, lang_norm: str) -> tuple[bool, str]:
    try:
        if lang_norm == "python":
            r = subprocess.run(
                [os.environ.get("THIRAMAI_PYTHON", "python"), "-m", "py_compile", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(path.parent),
            )
            ok = r.returncode == 0
            err = (r.stderr or r.stdout or "").strip()
            return ok, err[:2000]
        if lang_norm in ("javascript", "typescript", "react"):
            r = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(path.parent),
            )
            ok = r.returncode == 0
            err = (r.stderr or r.stdout or "").strip()
            return ok, err[:2000]
        return False, "unsupported language for syntax check"
    except FileNotFoundError as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, "syntax check timed out"


def _safe_target_path(target_path: str) -> Path:
    raw = (target_path or "").strip().replace("\\", "/")
    if not raw or ".." in raw or raw.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid target_path")
    dest = (REPO_ROOT / raw).resolve()
    try:
        dest.relative_to(REPO_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="target_path must stay inside repository") from None
    return dest


class GenerateBody(BaseModel):
    task: str = Field(..., min_length=3, max_length=4000)
    language: str = Field("python", max_length=32)
    context: str = Field("", max_length=8000)


@router.post("/code/generate", summary="Generate code with Groq + syntax check")
async def code_generate(body: GenerateBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        raise HTTPException(status_code=400, detail="Real user required")

    task_id = str(uuid.uuid4())
    fname, lang_norm = _language_filename(body.language)
    base = _agent_base_dir() / task_id
    base.mkdir(parents=True, exist_ok=True)
    fpath = base / fname

    try:
        code = await asyncio.to_thread(
            _groq_generate_code,
            task=body.task.strip(),
            language=body.language,
            context=(body.context or "").strip(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        _log.warning("groq generate failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"generation failed: {exc}") from exc

    if not code.strip():
        raise HTTPException(status_code=502, detail="empty generation")

    fpath.write_text(code, encoding="utf-8")
    syntax_ok, syn_err = _syntax_check(fpath, lang_norm)

    now = datetime.now(timezone.utc).isoformat()
    rec = {
        "id": task_id,
        "task": body.task.strip(),
        "language": body.language,
        "lang_norm": lang_norm,
        "context": (body.context or "").strip(),
        "code": code,
        "file_path": str(fpath),
        "relative_file": fname,
        "syntax_ok": syntax_ok,
        "syntax_error": syn_err if not syntax_ok else None,
        "status": "ready" if syntax_ok else "syntax_error",
        "created_at": now,
        "user_id": int(user.id),
        "last_test_output": None,
        "last_test_ok": None,
    }
    _TASKS[task_id] = rec
    _TASK_ORDER.append(task_id)
    if len(_TASK_ORDER) > 200:
        old = _TASK_ORDER.pop(0)
        _TASKS.pop(old, None)

    preview = code[:8000] + ("…" if len(code) > 8000 else "")
    return {
        "task_id": task_id,
        "code": code,
        "file_path": str(fpath),
        "syntax_ok": syntax_ok,
        "syntax_error": syn_err if not syntax_ok else None,
        "preview": preview,
    }


class TestBody(BaseModel):
    task_id: str = Field(..., min_length=8, max_length=64)


@router.post("/code/test", summary="Run generated code in subprocess (30s timeout)")
async def code_test(body: TestBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    rec = _TASKS.get(body.task_id.strip())
    if not rec or int(rec.get("user_id") or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="task not found")
    base = Path(rec["file_path"]).parent
    lang = rec.get("lang_norm") or "python"
    fname = Path(rec["file_path"]).name

    cmd: list[str]
    if lang == "python":
        cmd = [os.environ.get("THIRAMAI_PYTHON", "python"), fname]
    elif lang in ("javascript", "typescript", "react"):
        cmd = ["node", fname]
    else:
        cmd = [os.environ.get("THIRAMAI_PYTHON", "python"), fname]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        ok = proc.returncode == 0
        rec["last_test_ok"] = ok
        rec["last_test_output"] = out[-12000:]
        rec["status"] = "tested_ok" if ok else "tested_fail"
        return {"ok": ok, "output": out[-12000:], "errors": None if ok else f"exit {proc.returncode}"}
    except subprocess.TimeoutExpired:
        rec["last_test_ok"] = False
        rec["last_test_output"] = "(timeout)"
        rec["status"] = "tested_fail"
        return {"ok": False, "output": "", "errors": "timeout after 30s"}
    except Exception as exc:
        rec["last_test_ok"] = False
        rec["last_test_output"] = str(exc)
        return {"ok": False, "output": "", "errors": str(exc)}


class DeployBody(BaseModel):
    task_id: str = Field(..., min_length=8)
    target_path: str = Field(..., description="Relative path under repo root, e.g. app/generated/sample.py")
    confirmation_token: str = Field("", description="Must match THIRAMAI_CODE_AGENT_DEPLOY_TOKEN")


@router.post("/code/deploy", summary="Copy artifact into repo and git commit")
async def code_deploy(body: DeployBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    rec = _TASKS.get(body.task_id.strip())
    if not rec or int(rec.get("user_id") or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="task not found")

    if not _DEPLOY_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Deploy disabled: set THIRAMAI_CODE_AGENT_DEPLOY_TOKEN in environment.",
        )
    if body.confirmation_token.strip() != _DEPLOY_TOKEN:
        raise HTTPException(status_code=403, detail="invalid confirmation_token")

    src = Path(rec["file_path"])
    if not src.is_file():
        raise HTTPException(status_code=400, detail="source file missing")

    dest = _safe_target_path(body.target_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    git_hash = None
    committed = False
    try:
        rel = dest.relative_to(REPO_ROOT.resolve()).as_posix()
        subprocess.run(
            ["git", "add", "--", rel],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        cm = subprocess.run(
            ["git", "commit", "-m", f"code-agent: deploy {rec.get('task', '')[:60]}"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        committed = cm.returncode == 0
        gh = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if gh.returncode == 0:
            git_hash = (gh.stdout or "").strip()[:40]
    except FileNotFoundError:
        pass

    rec["status"] = "deployed"
    rec["deploy_path"] = str(dest)
    return {"ok": True, "committed": committed, "git_hash": git_hash, "path": str(dest)}


@router.get("/code/tasks", summary="List recent code generation tasks for current user")
async def list_tasks(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    uid = int(user.id)
    items: list[dict[str, Any]] = []
    for tid in reversed(_TASK_ORDER[-80:]):
        rec = _TASKS.get(tid)
        if not rec or int(rec.get("user_id") or 0) != uid:
            continue
        items.append(
            {
                "id": rec["id"],
                "task": rec.get("task"),
                "status": rec.get("status"),
                "created_at": rec.get("created_at"),
                "syntax_ok": rec.get("syntax_ok"),
            }
        )
    return {"tasks": items}


@router.get("/code/tasks/{task_id}", summary="Task detail")
async def task_detail(task_id: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    rec = _TASKS.get(task_id.strip())
    if not rec or int(rec.get("user_id") or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task": rec,
    }


class SelfHealBody(BaseModel):
    error_log: str = Field(..., min_length=4, max_length=16000)


@router.post("/self-heal", summary="Analyze error log and propose fix (Groq JSON)")
async def self_heal(body: SelfHealBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not configured")

    sys_msg = (
        "You analyze Python/Node runtime and deployment errors. "
        "Respond with a single JSON object only, keys: "
        "fix_type (pip_install|code_change|env|unknown), "
        "package (string or null), command (string or null), "
        "explanation (short string), needs_approval (boolean)."
    )
    user_msg = f"Error log:\n{body.error_log[:12000]}"

    from groq import Groq

    client = Groq(api_key=key)
    try:
        chat = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        text = (chat.choices[0].message.content or "").strip()
        data = json.loads(text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"analysis failed: {exc}") from exc

    fix_type = str(data.get("fix_type") or "unknown")
    package = data.get("package")
    cmd = data.get("command")
    if fix_type == "pip_install" and package and not cmd:
        cmd = f"pip install {package}"
    return {
        "fix_type": fix_type,
        "package": package,
        "command": cmd,
        "explanation": data.get("explanation"),
        "needs_approval": bool(data.get("needs_approval", True)),
    }


class SelfHealApplyBody(BaseModel):
    confirmation_token: str = ""
    command: str = Field(..., min_length=3, max_length=512)


@router.post("/self-heal/apply", summary="Run approved pip-style command (token-gated)")
async def self_heal_apply(body: SelfHealApplyBody, user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    _ = user
    if not _DEPLOY_TOKEN or body.confirmation_token.strip() != _DEPLOY_TOKEN:
        raise HTTPException(status_code=403, detail="invalid confirmation_token or deploy token not configured")

    cmd = body.command.strip()
    allowed = re.match(r"^pip(\d)?\s+install\s+.+", cmd, re.I) or re.match(r"^python\s+-m\s+pip\s+install\s+.+", cmd, re.I)
    if not allowed:
        raise HTTPException(status_code=400, detail="only pip install commands allowed")

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-8000:],
            "exit_code": proc.returncode,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _list_websites_sync(user_id: int, organization_id: int) -> list[dict[str, Any]]:
    factory = get_session_factory()
    if factory is None:
        return []
    out: list[dict[str, Any]] = []
    with factory() as session:
        mems = list_memberships_for_user(session, int(user_id))
        org_ids = {int(m.organization_id) for m in mems}
        if int(organization_id) > 0:
            org_ids.add(int(organization_id))
        for oid in sorted(org_ids):
            meta = get_generated_website_sync(int(oid))
            if not meta.get("ok"):
                out.append(
                    {
                        "organization_id": oid,
                        "name": f"Org #{oid}",
                        "status": "draft",
                        "url": None,
                        "slug": None,
                        "updated_at": None,
                    }
                )
                continue
            url = meta.get("public_url") or ""
            out.append(
                {
                    "organization_id": oid,
                    "name": f"Org #{oid}",
                    "status": "live" if url else "draft",
                    "url": url or None,
                    "slug": meta.get("slug"),
                    "updated_at": meta.get("updated_at"),
                }
            )
    # enrich org names
    try:
        from core.db.models import Organization

        with factory() as session:
            for row in out:
                oid = int(row["organization_id"])
                org = session.get(Organization, oid)
                if org is not None:
                    row["name"] = org.name
    except Exception:
        pass
    return out


@websites_router.get("/websites/list", summary="Websites / builder metadata per membership")
async def websites_list(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if int(user.id) <= 0:
        return {"ok": True, "websites": []}
    rows = await asyncio.to_thread(_list_websites_sync, int(user.id), int(user.organization_id))
    return {"ok": True, "websites": rows}
