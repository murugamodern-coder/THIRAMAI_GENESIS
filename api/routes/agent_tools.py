"""
Autonomous agent tool endpoints — shell (strict whitelist), file read/write under app root,
git snapshots, docker compose restarts.

All routes require JWT; executions are audit-logged and rate-limited per user.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user
from core.database import get_session_factory
from core.db.models import AuditLog
from services.audit_log import client_ip_from_request

_log = logging.getLogger("thiramai.api.agent_tools")

router = APIRouter(tags=["Agent tools"])

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolved_app_root() -> Path:
    raw = (os.getenv("THIRAMAI_AGENT_APP_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    docker_app = Path("/app")
    if docker_app.is_dir() and (docker_app / "app.py").is_file():
        return docker_app.resolve()
    return _REPO_ROOT.resolve()


APP_ROOT = _resolved_app_root()

ALLOWED_SHELL_PREFIXES = (
    "pip install",
    "pip list",
    "python -m",
    "git status",
    "git log",
    "alembic",
)

DISALLOWED_SHELL_SUBSTRINGS = ("rm -rf", "sudo", "curl", "wget")

SAFE_DOCKER_SERVICES = frozenset({"web", "worker-jobs"})

_TOOL_RATE_LOCK = threading.Lock()
_TOOL_RATE_HITS: dict[int, deque[float]] = defaultdict(deque)
_TOOL_RATE_WINDOW_SEC = 60.0
_TOOL_RATE_LIMIT = 10


def _tool_rate_allow(user_id: int) -> bool:
    now = time.monotonic()
    cutoff = now - _TOOL_RATE_WINDOW_SEC
    with _TOOL_RATE_LOCK:
        dq = _TOOL_RATE_HITS[user_id]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= _TOOL_RATE_LIMIT:
            return False
        dq.append(now)
        return True


async def require_tool_rate_limit(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    uid = int(user.id)
    if uid <= 0:
        return user
    if not _tool_rate_allow(uid):
        raise HTTPException(
            status_code=429,
            detail="Tool rate limit exceeded (max 10 calls per minute per user).",
        )
    return user


ToolUser = Annotated[CurrentUser, Depends(require_tool_rate_limit)]


def _audit_tool_execution(
    *,
    user: CurrentUser,
    request: Request | None,
    action_type: str,
    entity: str,
    result: str,
    meta: dict[str, Any],
) -> None:
    factory = get_session_factory()
    if factory is None:
        return
    ip = client_ip_from_request(request.client.host if request and request.client else None)
    ua = (request.headers.get("user-agent") if request else None) or ""
    row = AuditLog(
        organization_id=int(user.organization_id),
        user_id=int(user.id) if int(user.id) > 0 else None,
        action_type=str(action_type)[:128],
        entity=str(entity)[:128],
        entity_id=None,
        source="USER",
        result=str(result)[:16],
        audit_metadata={
            **meta,
            "client_ip": ip,
            "user_agent": (ua[:2000] if ua else ""),
        },
    )
    try:
        with factory() as session:
            session.add(row)
            session.commit()
    except Exception as exc:
        _log.warning("audit_logs insert failed: %s", type(exc).__name__)


def _dangerous_shell(command: str) -> bool:
    lower = command.lower()
    for bad in DISALLOWED_SHELL_SUBSTRINGS:
        if bad in lower:
            return True
    return False


def _shell_whitelisted(command: str) -> bool:
    if _dangerous_shell(command):
        return False
    c = " ".join(command.strip().split())
    lower = c.lower()
    for p in ALLOWED_SHELL_PREFIXES:
        if lower == p or lower.startswith(p + " "):
            return True
    if lower == "ls" or lower.startswith("ls "):
        return True
    if lower == "cat" or lower.startswith("cat "):
        return True
    return False


def _safe_resolve_under_app(path_raw: str) -> Path:
    p = Path(path_raw.strip()).expanduser()
    if not p.is_absolute():
        p = (APP_ROOT / p).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(APP_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path must be under application root.")
    return p


class ShellBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=8000)
    timeout: int = Field(30, ge=1, le=300)


class FileReadBody(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class FileWriteBody(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    content: str = Field(..., max_length=500_000)
    confirmation_token: str = Field(..., min_length=1, max_length=256)


class GitBody(BaseModel):
    action: Literal["status", "log", "diff"]


class DockerRestartBody(BaseModel):
    service: Literal["web", "worker-jobs"]


def _run_argv(command: str) -> list[str]:
    posix = os.name != "nt"
    return shlex.split(command.strip(), posix=posix)


def execute_shell_tool(
    *,
    user: CurrentUser,
    request: Request | None,
    command: str,
    timeout_sec: int,
) -> dict[str, Any]:
    if not _shell_whitelisted(command):
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.shell",
            entity="shell",
            result="FAIL",
            meta={"command_preview": command[:200], "reason": "not_whitelisted"},
        )
        raise HTTPException(status_code=400, detail="Command not permitted by whitelist.")

    argv = _run_argv(command)
    if not argv:
        raise HTTPException(status_code=400, detail="Empty command.")

    try:
        proc = subprocess.run(
            argv,
            cwd=str(APP_ROOT),
            capture_output=True,
            text=True,
            timeout=float(timeout_sec),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.shell",
            entity="shell",
            result="FAIL",
            meta={"command_preview": command[:200], "reason": "timeout"},
        )
        raise HTTPException(status_code=408, detail="Command timed out.")

    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    if len(out) > 100_000:
        out = out[:100_000] + "\n...[truncated]"

    _audit_tool_execution(
        user=user,
        request=request,
        action_type="agent_tool.shell",
        entity="shell",
        result="SUCCESS" if proc.returncode == 0 else "FAIL",
        meta={
            "command_preview": command[:200],
            "exit_code": proc.returncode,
        },
    )
    return {"ok": True, "output": out, "exit_code": proc.returncode}


def execute_file_read_tool(*, user: CurrentUser, request: Request | None, path_raw: str) -> dict[str, Any]:
    target = _safe_resolve_under_app(path_raw)
    if not target.is_file():
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.file_read",
            entity="file_read",
            result="FAIL",
            meta={"path": path_raw[:512]},
        )
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.file_read",
            entity="file_read",
            result="FAIL",
            meta={"path": path_raw[:512], "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail="Could not read file.") from exc

    lines = text.count("\n") + (0 if text.endswith("\n") else 1 if text else 0)
    _audit_tool_execution(
        user=user,
        request=request,
        action_type="agent_tool.file_read",
        entity="file_read",
        result="SUCCESS",
        meta={"path": str(target)[:512], "lines": lines},
    )
    return {"ok": True, "content": text, "lines": lines}


def execute_file_write_tool(
    *,
    user: CurrentUser,
    request: Request | None,
    path_raw: str,
    content: str,
    confirmation_token: str,
) -> dict[str, Any]:
    expected = (os.getenv("THIRAMAI_AGENT_FILE_WRITE_CONFIRM_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="File write is disabled (set THIRAMAI_AGENT_FILE_WRITE_CONFIRM_TOKEN).",
        )
    if confirmation_token.strip() != expected:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.file_write",
            entity="file_write",
            result="FAIL",
            meta={"path": path_raw[:512], "reason": "bad_token"},
        )
        raise HTTPException(status_code=403, detail="Invalid confirmation token.")

    target = _safe_resolve_under_app(path_raw)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.file_write",
            entity="file_write",
            result="FAIL",
            meta={"path": path_raw[:512], "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail="Could not write file.") from exc

    _audit_tool_execution(
        user=user,
        request=request,
        action_type="agent_tool.file_write",
        entity="file_write",
        result="SUCCESS",
        meta={"path": str(target)[:512], "bytes": len(content.encode("utf-8", errors="ignore"))},
    )
    return {"ok": True, "written": True}


def execute_git_tool(*, user: CurrentUser, request: Request | None, action: str) -> dict[str, Any]:
    if action == "status":
        argv = ["git", "status", "--porcelain=v1", "-b"]
    elif action == "log":
        argv = ["git", "log", "-n", "30", "--oneline", "--no-decorate"]
    else:
        argv = ["git", "diff", "--stat"]

    try:
        proc = subprocess.run(
            argv,
            cwd=str(APP_ROOT),
            capture_output=True,
            text=True,
            timeout=90.0,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.git",
            entity=f"git:{action}",
            result="FAIL",
            meta={"reason": "timeout"},
        )
        raise HTTPException(status_code=408, detail="Git command timed out.")

    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    if len(out) > 80_000:
        out = out[:80_000] + "\n...[truncated]"

    _audit_tool_execution(
        user=user,
        request=request,
        action_type="agent_tool.git",
        entity=f"git:{action}",
        result="SUCCESS" if proc.returncode == 0 else "FAIL",
        meta={"exit_code": proc.returncode},
    )
    return {"ok": proc.returncode == 0, "output": out}


def execute_docker_restart_tool(*, user: CurrentUser, request: Request | None, service: str) -> dict[str, Any]:
    if service not in SAFE_DOCKER_SERVICES:
        raise HTTPException(status_code=400, detail="Unsupported service.")

    compose_dir_raw = (os.getenv("THIRAMAI_COMPOSE_PROJECT_DIR") or "").strip()
    compose_dir = Path(compose_dir_raw).expanduser().resolve() if compose_dir_raw else APP_ROOT

    docker_exe = os.getenv("THIRAMAI_DOCKER_CLI") or "docker"
    cmd = [docker_exe, "compose", "restart", service]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(compose_dir),
            capture_output=True,
            text=True,
            timeout=180.0,
            shell=False,
        )
    except FileNotFoundError:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.docker_restart",
            entity=service,
            result="FAIL",
            meta={"reason": "docker_cli_missing"},
        )
        raise HTTPException(status_code=503, detail="Docker CLI not available on this host.")
    except subprocess.TimeoutExpired:
        _audit_tool_execution(
            user=user,
            request=request,
            action_type="agent_tool.docker_restart",
            entity=service,
            result="FAIL",
            meta={"reason": "timeout"},
        )
        raise HTTPException(status_code=408, detail="Docker restart timed out.")

    ok = proc.returncode == 0
    msg = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()

    _audit_tool_execution(
        user=user,
        request=request,
        action_type="agent_tool.docker_restart",
        entity=service,
        result="SUCCESS" if ok else "FAIL",
        meta={"exit_code": proc.returncode, "compose_dir": str(compose_dir)[:256], "output_preview": msg[:800]},
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg[:2000] or "Docker restart failed.")
    return {"ok": True, "restarted": True}


def dispatch_agent_tool(
    *,
    user: CurrentUser,
    request: Request | None,
    tool: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Run a tool by name (same behavior as HTTP). Used by Central Brain ACTION routing.
    Applies per-user rate limiting.
    """
    uid = int(user.id)
    if uid > 0 and not _tool_rate_allow(uid):
        return {"ok": False, "detail": "Tool rate limit exceeded (max 10 calls per minute per user)."}

    name = (tool or "").strip().lower().replace("-", "_")
    try:
        if name in ("shell",):
            cmd = str(params.get("command") or "").strip()
            to = int(params.get("timeout") or 30)
            return execute_shell_tool(user=user, request=request, command=cmd, timeout_sec=max(1, min(to, 300)))
        if name in ("file_read", "fileread"):
            return execute_file_read_tool(user=user, request=request, path_raw=str(params.get("path") or ""))
        if name in ("file_write", "filewrite"):
            return execute_file_write_tool(
                user=user,
                request=request,
                path_raw=str(params.get("path") or ""),
                content=str(params.get("content") or ""),
                confirmation_token=str(params.get("confirmation_token") or ""),
            )
        if name == "git":
            action = str(params.get("action") or "status").strip().lower()
            if action not in ("status", "log", "diff"):
                return {"ok": False, "detail": "Invalid git action."}
            return execute_git_tool(user=user, request=request, action=action)
        if name in ("docker_restart", "dockerrestart"):
            svc = str(params.get("service") or "").strip()
            return execute_docker_restart_tool(user=user, request=request, service=svc)
    except HTTPException as exc:
        return {"ok": False, "detail": exc.detail, "status_code": exc.status_code}
    return {"ok": False, "detail": f"Unknown tool: {tool}"}


@router.post("/shell")
async def tool_shell(body: ShellBody, request: Request, user: ToolUser) -> dict[str, Any]:
    return execute_shell_tool(
        user=user,
        request=request,
        command=body.command.strip(),
        timeout_sec=body.timeout,
    )


@router.post("/file/read")
async def tool_file_read(body: FileReadBody, request: Request, user: ToolUser) -> dict[str, Any]:
    return execute_file_read_tool(user=user, request=request, path_raw=body.path)


@router.post("/file/write")
async def tool_file_write(body: FileWriteBody, request: Request, user: ToolUser) -> dict[str, Any]:
    return execute_file_write_tool(
        user=user,
        request=request,
        path_raw=body.path,
        content=body.content,
        confirmation_token=body.confirmation_token,
    )


@router.post("/git")
async def tool_git(body: GitBody, request: Request, user: ToolUser) -> dict[str, Any]:
    return execute_git_tool(user=user, request=request, action=body.action)


@router.post("/docker/restart")
async def tool_docker_restart(body: DockerRestartBody, request: Request, user: ToolUser) -> dict[str, Any]:
    return execute_docker_restart_tool(user=user, request=request, service=body.service)
