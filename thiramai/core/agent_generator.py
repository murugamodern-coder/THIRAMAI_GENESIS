import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from thiramai.integrations.llm_clients import multi_llm


GENERATED_DIR = Path(__file__).resolve().parent.parent / "agents" / "generated"
REGISTRY_PATH = GENERATED_DIR / "agents_registry.json"
SAFE_AGENT_TYPES = {"research", "parser", "api"}


class AgentGenerator:
    def __init__(self) -> None:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        if not REGISTRY_PATH.exists():
            REGISTRY_PATH.write_text(
                json.dumps({"agents": []}, indent=2),
                encoding="utf-8",
            )

    def detect_capability_gap(
        self,
        task: dict[str, Any],
        result: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, str] | None:
        merged = " ".join(
            [
                str(task.get("description", "")),
                str(task.get("command", "")),
                str(result.get("error", "")),
                str(review.get("reason", "")),
            ]
        ).lower()

        if any(word in merged for word in {"web", "search", "external data", "need web data"}):
            return {"agent_type": "research", "purpose": "Collect web evidence safely for planning and review."}
        if any(word in merged for word in {"parse", "json", "csv", "yaml", "file parsing", "invalid output"}):
            return {"agent_type": "parser", "purpose": "Parse structured files and extract validated summaries."}
        if any(word in merged for word in {"api", "endpoint", "http", "request", "need api call"}):
            return {"agent_type": "api", "purpose": "Call HTTP APIs with safe read-focused behavior."}
        return None

    def generate_agent(self, agent_type: str, purpose: str) -> dict[str, Any]:
        normalized_type = agent_type.strip().lower()
        if normalized_type not in SAFE_AGENT_TYPES:
            raise ValueError(f"Unsupported generated agent type: {normalized_type}")

        class_name = f"{normalized_type.title()}GeneratedAgent"
        module_name = f"{normalized_type}_generated_agent"
        prompt = (
            "Create a concise JSON spec for a safe autonomous helper agent.\n"
            "Return strict JSON only with keys: summary, execute_steps.\n"
            "execute_steps must be a list of 3-6 short safe steps.\n"
            f"agent_type={normalized_type}\n"
            f"purpose={purpose}\n"
            "Do not include shell execution instructions."
        )
        raw = multi_llm(prompt)
        spec = self._safe_parse_spec(raw, purpose)

        source = self._build_agent_source(class_name=class_name, purpose=purpose, spec=spec)
        agent_path = GENERATED_DIR / f"{module_name}.py"
        agent_path.write_text(source, encoding="utf-8")

        registry = self._read_registry()
        existing = next((a for a in registry["agents"] if a.get("agent_name") == class_name), None)
        if existing:
            existing["purpose"] = purpose
            existing["module"] = module_name
            existing["usage_count"] = int(existing.get("usage_count", 0))
        else:
            registry["agents"].append(
                {
                    "agent_name": class_name,
                    "module": module_name,
                    "agent_type": normalized_type,
                    "purpose": purpose,
                    "usage_count": 0,
                }
            )
        self._write_registry(registry)
        return {"agent_name": class_name, "module": module_name, "path": str(agent_path)}

    def load_generated_agent(self, module_name: str, class_name: str) -> object:
        module_file = GENERATED_DIR / f"{module_name}.py"
        if not module_file.exists():
            raise FileNotFoundError(f"Generated agent module missing: {module_file}")
        spec = importlib.util.spec_from_file_location(f"thiramai.agents.generated.{module_name}", module_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load generated module spec for {module_name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        klass = getattr(module, class_name, None)
        if klass is None:
            raise RuntimeError(f"Generated class {class_name} missing in module {module_name}")
        print("[AGENT LOADED]")
        print(json.dumps({"module": module_name, "class_name": class_name}, ensure_ascii=True))
        return klass()

    def increment_usage(self, agent_name: str) -> None:
        registry = self._read_registry()
        for item in registry["agents"]:
            if item.get("agent_name") == agent_name:
                item["usage_count"] = int(item.get("usage_count", 0)) + 1
                break
        self._write_registry(registry)

    def get_best_agent_for_type(self, agent_type: str) -> dict[str, Any] | None:
        registry = self._read_registry()
        candidates = [a for a in registry["agents"] if a.get("agent_type") == agent_type]
        if not candidates:
            return None
        candidates.sort(key=lambda a: int(a.get("usage_count", 0)), reverse=True)
        return candidates[0]

    def _safe_parse_spec(self, raw: str, purpose: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(raw[start : end + 1])
            else:
                parsed = {}

        steps = parsed.get("execute_steps", [])
        if not isinstance(steps, list) or not steps:
            steps = [
                "Inspect the task payload for required fields.",
                "Apply deterministic parsing and safe data extraction.",
                "Return structured findings with risk notes.",
            ]
        steps = [str(step).strip() for step in steps[:6] if str(step).strip()]
        return {
            "summary": str(parsed.get("summary", purpose)).strip(),
            "execute_steps": steps,
        }

    def _build_agent_source(self, class_name: str, purpose: str, spec: dict[str, Any]) -> str:
        safe_purpose = purpose.replace('"', "'")
        summary = str(spec.get("summary", purpose)).replace('"', "'")
        steps = [re.sub(r"[^a-zA-Z0-9 .,;:_\-()]", "", step) for step in spec.get("execute_steps", [])]
        steps_literal = json.dumps(steps, ensure_ascii=True, indent=8)
        return (
            "from typing import Any\n\n\n"
            f"class {class_name}:\n"
            f"    PURPOSE = \"{safe_purpose}\"\n"
            f"    SUMMARY = \"{summary}\"\n\n"
            "    def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:\n"
            f"        execution_steps = {steps_literal}\n"
            "        observed = {\n"
            "            \"task_type\": str(task.get(\"type\", \"\")),\n"
            "            \"description\": str(task.get(\"description\", \"\")),\n"
            "            \"command\": str(task.get(\"command\", \"\")),\n"
            "        }\n"
            "        # Generated agents are intentionally non-executing and policy-safe.\n"
            "        return {\n"
            "            \"ok\": True,\n"
            "            \"status\": \"success\",\n"
            "            \"returncode\": 0,\n"
            "            \"output\": \"Generated agent completed safe analytical execution.\",\n"
            "            \"error\": \"\",\n"
            "            \"agent_summary\": self.SUMMARY,\n"
            "            \"agent_purpose\": self.PURPOSE,\n"
            "            \"execution_steps\": execution_steps,\n"
            "            \"observed\": observed,\n"
            "        }\n"
        )

    def _read_registry(self) -> dict[str, Any]:
        raw = REGISTRY_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            return {"agents": []}
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("agents", []), list):
            return parsed
        return {"agents": []}

    def _write_registry(self, data: dict[str, Any]) -> None:
        REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
