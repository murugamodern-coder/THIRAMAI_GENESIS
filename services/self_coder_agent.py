"""
Self-Coder agent: samples ``core/`` and ``services/``, asks the LLM for a unified diff,
writes ``var/sandbox_patches/candidate.patch``, runs pytest in the Docker sandbox, and
publishes a hot-reload signal when tests pass.

**Dangerous** — gated by ``THIRAMAI_SELF_CODER=1`` and owner-only API. Never executes
generated code on the host; only inside ``sandbox_service.run_pytest_in_sandbox``.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.kernel import bridge
from core.kernel import hot_reload
from core.observability import log_structured
from services import sandbox_service


def self_coder_enabled() -> bool:
    return (os.getenv("THIRAMAI_SELF_CODER") or "").strip().lower() in ("1", "true", "yes", "on")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def collect_code_context(*, max_files: int = 24, max_chars_per_file: int = 4000) -> str:
    """Concatenate bounded excerpts from ``core/*.py`` and ``services/*.py`` (shallow)."""
    parts: list[str] = []
    n = 0
    for sub in ("core", "services"):
        base = repo_root() / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if n >= max_files:
                break
            rel = path.relative_to(repo_root())
            if "kernel" in rel.parts and "test" in rel.name:
                continue
            if path.name.startswith("test_"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > max_chars_per_file:
                text = text[:max_chars_per_file] + "\n# ... truncated ...\n"
            parts.append(f"### FILE {rel.as_posix()}\n```python\n{text}\n```\n")
            n += 1
        if n >= max_files:
            break
    return "\n".join(parts) if parts else "(no files collected)"


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def patch_targets_allowed(diff: str) -> tuple[bool, str]:
    """Reject paths outside ``core/`` and ``services/`` or with traversal."""
    for line in diff.splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw = line[4:].strip().split("\t", 1)[0]
        path = raw.removeprefix("a/").removeprefix("b/")
        if path in ("/dev/null", "dev/null"):
            continue
        if ".." in path or (path.startswith("/") and path != "/dev/null"):
            return False, f"rejected path: {path!r}"
        ok = path.startswith("core/") or path.startswith("services/")
        if not ok:
            return False, f"only core/ and services/ allowed, got {path!r}"
    return True, "ok"


def generate_patch_with_groq(*, focus_hint: str = "") -> tuple[bool, str, str]:
    """
    Returns (ok, patch_text_or_error, model_note).

    Requires ``GROQ_API_KEY``. Output must be a unified diff touching only ``core/`` or ``services/``.
    """
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return False, "", "GROQ_API_KEY missing"

    from groq import Groq

    ctx = collect_code_context()
    sys_msg = (
        "You are a senior Python maintainer. Propose a minimal unified diff (git format) "
        "that optimizes or fixes issues in the given THIRAMAI codebase. "
        "Rules: (1) touch ONLY files under core/ or services/ — no other paths. "
        "(2) No new dependencies. (3) Output ONLY the raw diff text, no markdown fences, no commentary. "
        "(4) Keep changes small and test-safe.\n\n"
        + bridge.describe_kernel()
    )
    user_msg = f"Codebase excerpts:\n\n{ctx}\n"
    if focus_hint.strip():
        user_msg += f"\nOwner focus: {focus_hint.strip()}\n"

    client = Groq(api_key=key)
    model = (os.getenv("THIRAMAI_SELF_CODER_MODEL") or "llama-3.3-70b-versatile").strip()
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg[:120_000]},
        ],
        temperature=0.15,
        max_tokens=8192,
    )
    choice = completion.choices[0].message.content or ""
    patch = _strip_fences(choice)
    if not patch.strip() or not patch.lstrip().startswith("diff "):
        return False, patch, "model did not return a unified diff starting with 'diff '"
    ok, reason = patch_targets_allowed(patch)
    if not ok:
        return False, patch, reason
    return True, patch, f"model={model}"


def write_candidate_patch(patch_text: str) -> Path:
    path = sandbox_service.candidate_patch_path()
    path.write_text(patch_text, encoding="utf-8")
    return path


def run_pipeline(
    *,
    focus_hint: str = "",
    pytest_targets: str = "tests/test_smoke.py tests/test_production_safety.py",
) -> dict:
    """
    Full Self-Coder cycle: generate patch → write candidate → sandbox pytest → hot_reload signal if green.
    """
    log_structured("self_coder.pipeline_start", focus=focus_hint[:200] or None)
    if not self_coder_enabled():
        return {"ok": False, "stage": "flag", "error": "THIRAMAI_SELF_CODER not enabled"}
    if not sandbox_service.sandbox_enabled():
        return {"ok": False, "stage": "sandbox_flag", "error": "THIRAMAI_KERNEL_SANDBOX not enabled"}

    ok, patch, note = generate_patch_with_groq(focus_hint=focus_hint)
    if not ok:
        log_structured("self_coder.generate_failed", detail=note[:500])
        return {"ok": False, "stage": "generate", "error": note, "patch_preview": patch[:500]}

    write_candidate_patch(patch)
    code, log_text = sandbox_service.run_pytest_in_sandbox(pytest_targets=pytest_targets)
    rel = "var/sandbox_patches/candidate.patch"
    if code == 0:
        hot_reload.publish_hot_reload(
            patch_relative_path=rel,
            pytest_exit_code=code,
            log_tail=log_text,
        )
        log_structured(
            "self_coder.pytest_passed",
            pytest_exit_code=code,
            patch_relative_path=rel,
            detail=note,
        )
        try:
            from core.sovereign_journal import record_background_action

            record_background_action(
                category="self_coder",
                summary=f"Sandbox pytest green; patch {rel} ({note[:200]})",
                organization_id=None,
                meta={"pytest_exit_code": code},
            )
        except Exception:
            pass
        return {
            "ok": True,
            "stage": "complete",
            "pytest_exit_code": code,
            "patch_path": rel,
            "hot_reload": "signalled",
            "model_note": note,
            "log_tail": log_text[-4000:],
        }

    log_structured("self_coder.pytest_failed", pytest_exit_code=code)
    return {
        "ok": False,
        "stage": "pytest",
        "pytest_exit_code": code,
        "error": "pytest failed in sandbox",
        "log_tail": log_text[-8000:],
        "model_note": note,
    }
