"""Tool Builder Agent: generate/test/deploy helper tools with governance gates."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.governance_engine import validate_action

_REGISTRY: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_path(tool_id: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "generated_tools" / f"{tool_id}.py"


def generate_tool_spec(goal_context: dict[str, Any]) -> dict[str, Any]:
    name = str(goal_context.get("name") or "autonomous_tool").strip().replace(" ", "_").lower()
    desc = str(goal_context.get("description") or "Generated helper tool")
    return {"ok": True, "tool_name": name[:80], "description": desc[:400], "inputs": goal_context.get("inputs") or []}


def generate_tool_code(tool_spec: dict[str, Any], user_id: int) -> dict[str, Any]:
    tool_id = f"tool_{len(_REGISTRY) + 1}_{int(datetime.now(timezone.utc).timestamp())}"
    tool_name = str(tool_spec.get("tool_name") or "autonomous_tool")
    description = str(tool_spec.get("description") or "Generated tool")
    code = (
        '"""Auto-generated Thiramai helper tool."""\n\n'
        "from __future__ import annotations\n\n"
        "def run(payload: dict) -> dict:\n"
        f"    \"\"\"{description}\"\"\"\n"
        "    return {\n"
        '        "ok": True,\n'
        f'        "tool": "{tool_name}",\n'
        '        "echo": payload or {},\n'
        "    }\n"
    )
    _REGISTRY[tool_id] = {
        "tool_id": tool_id,
        "tool_name": tool_name,
        "description": description,
        "code": code,
        "status": "generated",
        "created_by": int(user_id),
        "created_at": _now_iso(),
        "last_test": None,
    }
    return {"ok": True, "tool_id": tool_id, "status": "generated"}


def sandbox_test_tool(tool_id: str, user_id: int) -> dict[str, Any]:
    row = _REGISTRY.get(str(tool_id or ""))
    if not row:
        return {"ok": False, "error": "Tool not found"}
    if int(row.get("created_by") or 0) != int(user_id):
        return {"ok": False, "error": "Access denied"}
    try:
        compiled = compile(str(row.get("code") or ""), filename=f"{tool_id}.py", mode="exec")
        glb: dict[str, Any] = {}
        exec(compiled, glb)  # controlled generated snippet
        fn = glb.get("run")
        result = fn({"sandbox": True}) if callable(fn) else {"ok": False, "error": "No run()"}
        row["last_test"] = {"ok": bool((result or {}).get("ok")), "result": result, "tested_at": _now_iso()}
        row["status"] = "tested" if bool((result or {}).get("ok")) else "failed_test"
        return {"ok": True, "tool_id": tool_id, "test": row["last_test"], "status": row["status"]}
    except Exception as exc:
        row["last_test"] = {"ok": False, "error": str(exc), "tested_at": _now_iso()}
        row["status"] = "failed_test"
        return {"ok": False, "tool_id": tool_id, "error": str(exc)}


def deploy_tool(tool_id: str, user_id: int) -> dict[str, Any]:
    row = _REGISTRY.get(str(tool_id or ""))
    if not row:
        return {"ok": False, "error": "Tool not found"}
    if int(row.get("created_by") or 0) != int(user_id):
        return {"ok": False, "error": "Access denied"}
    check = validate_action(
        "tool_deploy",
        {"user_id": int(user_id), "domain": "automation", "payload": {"tool_id": str(tool_id)}},
    )
    if not check.get("allowed"):
        row["status"] = "blocked"
        return {"ok": False, "blocked": True, "reason": check.get("reason") or "Governance blocked"}
    if not bool((row.get("last_test") or {}).get("ok")):
        return {"ok": False, "error": "Tool must pass sandbox test before deploy"}
    p = _tool_path(str(tool_id))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(row.get("code") or ""), encoding="utf-8")
    row["status"] = "deployed"
    row["deployed_at"] = _now_iso()
    row["deploy_path"] = str(p)
    return {"ok": True, "tool_id": tool_id, "status": "deployed", "path": str(p)}


def tool_build_status(tool_id: str, user_id: int) -> dict[str, Any]:
    row = _REGISTRY.get(str(tool_id or ""))
    if not row:
        return {"ok": False, "error": "Tool not found"}
    if int(row.get("created_by") or 0) != int(user_id):
        return {"ok": False, "error": "Access denied"}
    return {
        "ok": True,
        "tool_id": str(tool_id),
        "tool_name": row.get("tool_name"),
        "status": row.get("status"),
        "last_test": row.get("last_test"),
        "deployed_at": row.get("deployed_at"),
        "deploy_path": row.get("deploy_path"),
    }
