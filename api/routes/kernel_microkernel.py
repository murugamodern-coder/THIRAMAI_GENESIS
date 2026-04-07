"""
Micro-kernel API: Docker sandbox pytest + Self-Coder agent + hot-reload signal management.

**Disabled by default.** Enable with ``THIRAMAI_KERNEL_API=1``. Self-Coder additionally requires
``THIRAMAI_SELF_CODER=1`` and ``THIRAMAI_KERNEL_SANDBOX=1``. Owner role only.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import require_roles
from core.kernel.bridge import kernel_capabilities
from core.kernel import hot_reload
from services import sandbox_service
from services import self_coder_agent

router = APIRouter(prefix="/kernel", tags=["Micro-kernel"])


def _kernel_api_on() -> bool:
    return (os.getenv("THIRAMAI_KERNEL_API") or "").strip().lower() in ("1", "true", "yes", "on")


def _require_kernel_api() -> None:
    if not _kernel_api_on():
        raise HTTPException(status_code=404, detail="Kernel API disabled (set THIRAMAI_KERNEL_API=1)")


class SelfCoderBody(BaseModel):
    focus_hint: str = Field("", max_length=2000, description="Optional guidance for the model")
    pytest_targets: str = Field(
        "tests/test_smoke.py tests/test_production_safety.py",
        max_length=500,
        description="Pytest target string passed inside the sandbox",
    )


class SandboxPytestBody(BaseModel):
    patch_unified_diff: str | None = Field(
        None,
        max_length=500_000,
        description="Optional unified diff written to candidate.patch before pytest",
    )
    pytest_targets: str = Field(
        "tests/test_smoke.py tests/test_production_safety.py",
        max_length=500,
    )


@router.get("/status")
def kernel_status(_: object = Depends(require_roles("owner"))) -> dict:
    _require_kernel_api()
    return {
        "kernel": kernel_capabilities(),
        "sandbox": sandbox_service.health(),
        "hot_reload_pending": hot_reload.peek_pending(),
        "flags": {
            "THIRAMAI_KERNEL_API": _kernel_api_on(),
            "THIRAMAI_KERNEL_SANDBOX": sandbox_service.sandbox_enabled(),
            "THIRAMAI_SELF_CODER": self_coder_agent.self_coder_enabled(),
        },
    }


@router.post("/reload/ack")
def kernel_reload_ack(_: object = Depends(require_roles("owner"))) -> dict:
    _require_kernel_api()
    hot_reload.clear_pending()
    return {"ok": True, "cleared": True}


@router.post("/sandbox/pytest")
def kernel_sandbox_pytest(
    body: SandboxPytestBody,
    _: object = Depends(require_roles("owner")),
) -> dict:
    _require_kernel_api()
    if not sandbox_service.sandbox_enabled():
        raise HTTPException(status_code=400, detail="THIRAMAI_KERNEL_SANDBOX not enabled")
    if body.patch_unified_diff is not None:
        if body.patch_unified_diff.strip():
            ok, reason = self_coder_agent.patch_targets_allowed(body.patch_unified_diff)
            if not ok:
                raise HTTPException(status_code=400, detail=reason)
            sandbox_service.candidate_patch_path().write_text(
                body.patch_unified_diff, encoding="utf-8"
            )
        else:
            sandbox_service.candidate_patch_path().write_text("", encoding="utf-8")

    code, log_text = sandbox_service.run_pytest_in_sandbox(pytest_targets=body.pytest_targets.strip())
    out: dict = {"ok": code == 0, "pytest_exit_code": code, "log_tail": log_text[-8000:]}
    if code == 0 and body.patch_unified_diff and body.patch_unified_diff.strip():
        hot_reload.publish_hot_reload(
            patch_relative_path="var/sandbox_patches/candidate.patch",
            pytest_exit_code=code,
            log_tail=log_text,
        )
        out["hot_reload"] = "signalled"
    return out


@router.post("/self-coder/run")
def kernel_self_coder_run(
    body: SelfCoderBody,
    _: object = Depends(require_roles("owner")),
) -> dict:
    _require_kernel_api()
    if not self_coder_agent.self_coder_enabled():
        raise HTTPException(status_code=400, detail="THIRAMAI_SELF_CODER not enabled")
    return self_coder_agent.run_pipeline(
        focus_hint=body.focus_hint,
        pytest_targets=body.pytest_targets.strip(),
    )
