"""
Autonomous CI/CD hooks after a **sandbox-approved** patch (pytest green + hot-reload signal).

Modes (``THIRAMAI_CI_CD_MODE``):
- ``github_dispatch`` — ``repository_dispatch`` to GitHub (requires PAT + repo full name).
- ``local_script`` — run ``THIRAMAI_DEPLOY_SCRIPT`` (bash/PowerShell path) with env vars set.
- unset / ``none`` — no-op (default).

Secrets must never be logged. When ``publish_hot_reload`` runs, it can invoke this module if
``THIRAMAI_CI_CD_ON_HOT_RELOAD`` (or legacy ``THIRAMAI_CICD_ON_HOT_RELOAD``) is set to ``1`` and
``THIRAMAI_CI_CD_MODE`` is ``github_dispatch`` or ``local_script``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.observability import log_structured


def ci_cd_mode() -> str:
    return (os.getenv("THIRAMAI_CI_CD_MODE") or "none").strip().lower()


def trigger_after_sandbox_approval(
    *,
    patch_relative_path: str,
    pytest_exit_code: int,
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fire CI/CD when sandbox tests pass (Reviewer-equivalent gate).

    Returns a dict with ``ok``, ``channel``, and non-sensitive detail.
    """
    mode = ci_cd_mode()
    payload = {
        "patch_relative_path": patch_relative_path,
        "pytest_exit_code": pytest_exit_code,
        "source": source,
        **(extra or {}),
    }
    log_structured(
        "ci_cd.trigger_request",
        mode=mode or "none",
        source=source,
        pytest_exit_code=pytest_exit_code,
    )
    if mode in ("", "none", "off", "0"):
        return {"ok": True, "channel": "skipped", "detail": "THIRAMAI_CI_CD_MODE not set"}

    if mode == "github_dispatch":
        return _github_repository_dispatch(payload)

    if mode == "local_script":
        return _run_local_deploy_script(payload)

    return {"ok": False, "channel": "unknown_mode", "detail": f"unknown THIRAMAI_CI_CD_MODE={mode!r}"}


def _github_repository_dispatch(client_payload: dict[str, Any]) -> dict[str, Any]:
    token = (os.getenv("THIRAMAI_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    repo = (os.getenv("THIRAMAI_GITHUB_REPO") or "").strip()
    event = (os.getenv("THIRAMAI_GITHUB_DISPATCH_EVENT") or "kernel-patch-approved").strip()
    if not token or not repo or "/" not in repo:
        return {
            "ok": False,
            "channel": "github_dispatch",
            "detail": "THIRAMAI_GITHUB_TOKEN and THIRAMAI_GITHUB_REPO (owner/name) required",
        }
    url = f"https://api.github.com/repos/{repo}/dispatches"
    body = {"event_type": event, "client_payload": client_payload}
    try:
        import httpx

        r = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=body,
            timeout=45.0,
        )
    except Exception as exc:
        log_structured("ci_cd.github_dispatch_error", error_type=type(exc).__name__)
        return {"ok": False, "channel": "github_dispatch", "detail": type(exc).__name__}
    if r.status_code not in (204, 200):
        log_structured("ci_cd.github_dispatch_http", status_code=r.status_code)
        return {
            "ok": False,
            "channel": "github_dispatch",
            "detail": f"HTTP {r.status_code}",
        }
    log_structured("ci_cd.github_dispatch_ok", event_type=event)
    return {"ok": True, "channel": "github_dispatch", "detail": "repository_dispatch accepted"}


def _run_local_deploy_script(client_payload: dict[str, Any]) -> dict[str, Any]:
    script = (os.getenv("THIRAMAI_DEPLOY_SCRIPT") or "").strip()
    if not script:
        default_sh = Path(__file__).resolve().parents[1] / "scripts" / "ci_cd_after_kernel.sh"
        if sys.platform == "win32":
            script = str(Path(__file__).resolve().parents[1] / "scripts" / "ci_cd_after_kernel.ps1")
        else:
            script = str(default_sh)
    path = Path(script)
    if not path.is_file():
        return {"ok": False, "channel": "local_script", "detail": f"script not found: {script}"}
    env = os.environ.copy()
    env["THIRAMAI_KERNEL_PAYLOAD_JSON"] = json.dumps(client_payload, ensure_ascii=False)[:12000]
    try:
        if str(path).lower().endswith(".ps1"):
            p = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                cwd=str(path.parent.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        else:
            p = subprocess.run(
                ["/bin/bash", str(path)],
                cwd=str(path.parent.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,
            )
    except subprocess.TimeoutExpired:
        return {"ok": False, "channel": "local_script", "detail": "timeout"}
    except Exception as exc:
        return {"ok": False, "channel": "local_script", "detail": type(exc).__name__}
    ok = p.returncode == 0
    tail = (p.stdout or "")[-2000:] + (p.stderr or "")[-2000:]
    log_structured(
        "ci_cd.local_script_done",
        ok=ok,
        returncode=p.returncode,
    )
    return {
        "ok": ok,
        "channel": "local_script",
        "detail": tail[-500:] if not ok else "completed",
        "returncode": p.returncode,
    }
