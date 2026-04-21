"""
THIRAMAI self-healing: analyze runtime errors, propose fixes via LLM,
apply patches only under the `thiramai/` package with backup + rollback.
Tests use the hardened Executor (shell=False, allowlist).
"""

from __future__ import annotations

import json
import re
import shutil
import time
import traceback
from pathlib import Path
from typing import Any

from thiramai.config import THIRAMAI_SANDBOX_MODE, get_thiramai_mode
from thiramai.core.executor import Executor
from thiramai.core.sandbox import sandbox_py_compile
from thiramai.integrations.llm_clients import call_llm

# Only files inside this directory may be modified.
THIRAMAI_PKG_ROOT = Path(__file__).resolve().parent.parent


def analyze_error(log: str, code_context: str) -> dict[str, Any]:
    """
    Use LLM to infer root cause, affected file (relative to repo: thiramai/...), and strategy.
    """
    prompt = (
        "You are a senior Python SRE. Given a runtime error log and code excerpt, respond with "
        "STRICT JSON only (no markdown):\n"
        '{"root_cause":"string","affected_file":"thiramai/relative/path.py or empty",'
        '"fix_strategy":"short actionable plan"}\n'
        f"ERROR_LOG:\n{log[:8000]}\n\nCODE_CONTEXT:\n{code_context[:12000]}\n"
        "Rules: affected_file must be under thiramai/ and be a .py file, or empty if unknown."
    )
    raw = call_llm(prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(raw[start : end + 1])
        else:
            parsed = {}
    return {
        "root_cause": str(parsed.get("root_cause", "unknown")).strip(),
        "affected_file": str(parsed.get("affected_file", "")).strip().replace("\\", "/"),
        "fix_strategy": str(parsed.get("fix_strategy", "minimal targeted fix")).strip(),
    }


def generate_code_fix(error_analysis: dict[str, Any]) -> str:
    """
    Ask LLM for a complete replacement Python module (valid syntax, production style).
    Reads current file from affected_file when resolvable.
    """
    rel = error_analysis.get("affected_file", "")
    target = _resolve_affected_file(rel) if rel else None
    original_source = ""
    if target and target.exists():
        original_source = target.read_text(encoding="utf-8", errors="replace")
    prompt = (
        "You are a senior Python engineer. Output ONLY valid Python source code for the ENTIRE file.\n"
        "No markdown fences, no prose before or after the code.\n"
        f"File: {rel}\n"
        f"Root cause: {error_analysis.get('root_cause', '')}\n"
        f"Fix strategy: {error_analysis.get('fix_strategy', '')}\n\n"
        "CURRENT_FILE_CONTENT:\n"
        f"{original_source[:20000] or '(empty or unknown file)'}\n"
    )
    raw = call_llm(prompt).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:python)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip() + ("\n" if raw and not raw.endswith("\n") else "")


def apply_patch(file_path: Path, new_code: str) -> Path:
    """
    Backup existing file, then overwrite with new_code. Returns path to backup file.
    """
    file_path = file_path.resolve()
    if not _is_patchable_path(file_path):
        raise ValueError(f"Refusing to patch outside thiramai package: {file_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Target file does not exist: {file_path}")

    backup = file_path.with_suffix(file_path.suffix + f".bak.selfheal.{int(time.time())}")
    shutil.copy2(file_path, backup)

    tmp = file_path.with_suffix(file_path.suffix + ".tmp.selfheal")
    tmp.write_text(new_code, encoding="utf-8")
    tmp.replace(file_path)
    return backup


def _is_patchable_path(path: Path) -> bool:
    try:
        path.relative_to(THIRAMAI_PKG_ROOT.resolve())
        return path.suffix == ".py"
    except ValueError:
        return False


def _resolve_affected_file(rel: str) -> Path | None:
    if not rel or not rel.endswith(".py"):
        return None
    raw = Path(rel.replace("\\", "/"))
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        rel_norm = str(raw).lstrip("/")
        if rel_norm.startswith("thiramai/"):
            rel_norm = rel_norm[len("thiramai/") :]
        candidate = (THIRAMAI_PKG_ROOT / rel_norm).resolve()
    if _is_patchable_path(candidate) and candidate.exists():
        return candidate
    return None


def test_fix(executor: Executor, relative_py: str) -> dict[str, Any]:
    """
    Run `python -m py_compile <path>` via Executor (allowlisted, no shell).
    relative_py: e.g. thiramai/main.py from repository root (parent of thiramai package).
    """
    rel = relative_py.replace("\\", "/").lstrip("/")
    if ".." in rel or rel.startswith("/"):
        return {"passed": False, "error": "Invalid relative path for compile test."}
    cmd = f"python -m py_compile {rel}"
    return executor.execute_command(cmd)


def rollback(backup_path: Path, target_path: Path) -> None:
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup missing: {backup_path}")
    shutil.copy2(backup_path, target_path)


class SelfHealer:
    """Orchestrates analyze → generate → apply → test → rollback on failure."""

    def __init__(self, executor: Executor) -> None:
        self.executor = executor
        self._last_backup: Path | None = None
        self._last_target: Path | None = None

    def heal_from_exception(self, exc: BaseException, tb_text: str | None = None) -> dict[str, Any]:
        tb_text = tb_text or traceback.format_exc()
        print("[ERROR DETECTED]")
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=True))
        if get_thiramai_mode() == "dry-run":
            return {"ok": False, "skipped": True, "reason": "dry-run: self-heal patch pipeline disabled"}

        affected_rel = self._extract_file_from_traceback(tb_text)
        code_context = ""
        target: Path | None = None
        if affected_rel:
            target = _resolve_affected_file(affected_rel)
            if target and target.exists():
                code_context = target.read_text(encoding="utf-8", errors="replace")[:15000]

        analysis = analyze_error(
            log=f"{type(exc).__name__}: {exc}\n\n{tb_text}",
            code_context=code_context or "(no file context)",
        )
        rel_for_compile = ""
        if target is None and analysis.get("affected_file"):
            target = _resolve_affected_file(analysis["affected_file"])
            if target and target.exists():
                code_context = target.read_text(encoding="utf-8", errors="replace")[:15000]
        if target is None:
            print("[FIX GENERATED]")
            print(json.dumps({"skipped": True, "reason": "no patchable affected_file"}, ensure_ascii=True))
            return {"ok": False, "skipped": True, "analysis": analysis}

        try:
            rel_for_compile = str(target.relative_to(THIRAMAI_PKG_ROOT.parent))
        except ValueError:
            rel_for_compile = "thiramai/" + str(target.relative_to(THIRAMAI_PKG_ROOT)).replace("\\", "/")

        analysis["affected_file"] = rel_for_compile.replace("\\", "/")
        new_source = generate_code_fix(analysis)
        print("[FIX GENERATED]")
        print(json.dumps({"bytes": len(new_source), "file": str(target)}, ensure_ascii=True))

        try:
            compile(new_source, str(target), "exec")
        except SyntaxError as syn:
            print("[TEST RESULT]")
            print(json.dumps({"passed": False, "phase": "syntax_check", "error": str(syn)}, ensure_ascii=True))
            return {"ok": False, "analysis": analysis, "error": f"syntax: {syn}"}

        sandbox_dir = THIRAMAI_PKG_ROOT / "data" / ".sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        candidate_name = f"candidate_{int(time.time())}_{target.name}"
        candidate_path = sandbox_dir / candidate_name
        candidate_path.write_text(new_source, encoding="utf-8")
        rel_candidate = f"thiramai/data/.sandbox/{candidate_name}".replace("\\", "/")

        if THIRAMAI_SANDBOX_MODE != "live":
            print("[SANDBOX TEST]")
            sandbox_result = sandbox_py_compile(rel_candidate)
            print(json.dumps(sandbox_result, ensure_ascii=True))
            passed_sb = sandbox_result.get("status") == "success" and sandbox_result.get("returncode", -1) == 0
            if not passed_sb:
                print("[TEST RESULT]")
                print(json.dumps({"passed": False, "phase": "sandbox_pre_apply"}, ensure_ascii=True))
                return {
                    "ok": False,
                    "analysis": analysis,
                    "sandbox": sandbox_result,
                    "phase": "sandbox_pre_apply",
                }

        print("[PATCH APPLIED]")
        backup = apply_patch(target, new_source)
        self._last_backup = backup
        self._last_target = target
        print(json.dumps({"target": str(target), "backup": str(backup)}, ensure_ascii=True))

        test_result = test_fix(self.executor, rel_for_compile)
        passed = test_result.get("status") == "success" and test_result.get("returncode", -1) == 0
        print("[TEST RESULT]")
        print(json.dumps({"passed": passed, "detail": test_result}, ensure_ascii=True))

        if not passed:
            print("[ROLLBACK]")
            rollback(backup, target)
            print(json.dumps({"restored_from": str(backup)}, ensure_ascii=True))
            self._last_backup = None
            self._last_target = None
            return {"ok": False, "analysis": analysis, "test": test_result, "rolled_back": True}

        return {"ok": True, "analysis": analysis, "test": test_result, "backup": str(backup)}

    @staticmethod
    def _extract_file_from_traceback(tb: str) -> str:
        for line in tb.splitlines():
            m = re.search(r'File "([^"]+\.py)"', line)
            if m:
                return m.group(1)
        return ""
