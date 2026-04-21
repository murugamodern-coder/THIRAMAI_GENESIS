import json
from typing import Any

from thiramai.agents.base import CoderAgent, MessageBus, ResearcherAgent, ReviewerAgent
from thiramai.core.knowledge import LocalKnowledgeBase
from thiramai.core.system_awareness import system_scan_compact
from thiramai.integrations.llm_clients import call_llm_structured
from thiramai.schemas.contracts import PlanModel, StepModel


class Planner:
    def __init__(self) -> None:
        self.knowledge = LocalKnowledgeBase()

    def create_plan(
        self,
        goal: str,
        past_failures: list[dict[str, Any]] | None = None,
        learning_snapshot: dict[str, Any] | None = None,
        realtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        failures = past_failures or []
        learning = learning_snapshot or {"failures": [], "success_patterns": [], "learned_rules": []}
        context = realtime_context or {}
        system_snapshot = system_scan_compact()
        optimized_strategy = self.optimize_strategy(goal, learning)
        past_similar: list[dict[str, Any]] = []
        try:
            from thiramai.core.memory import MemoryStore

            past_similar = MemoryStore().search_past_solutions_hybrid(goal, limit=6)
        except Exception:
            past_similar = []
        past_line = ""
        if past_similar:
            past_line = (
                "Similar past episodes (reuse successful patterns where applicable): "
                f"{json.dumps(past_similar, ensure_ascii=True)}\n"
            )
            top = past_similar[0]
            try:
                sc = float(top.get("score", 0) or 0)
            except (TypeError, ValueError):
                sc = 0.0
            if sc >= 0.35:
                past_line += f"Best match (highest score): {json.dumps(top, ensure_ascii=True)[:2000]}\n"
        knowledge_hits = self.knowledge.retrieve(goal, limit=4)
        knowledge_line = ""
        if knowledge_hits:
            knowledge_line = (
                "Relevant local knowledge snippets (prioritize these before web search): "
                f"{json.dumps(knowledge_hits, ensure_ascii=True)}\n"
            )
        prompt = (
            "You are a goal-driven autonomous planner.\n"
            "Return ONLY strict JSON using this schema:\n"
            '{\n'
            '  "goal": "string",\n'
            '  "total_steps": 1,\n'
            '  "steps": [\n'
            "    {\n"
            '      "id": 1,\n'
            '      "task_type": "audit|analysis|coding|research|fix|api|device",\n'
            '      "description": "string",\n'
            '      "command": "safe shell command or empty string",\n'
            '      "depends_on": [1]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Keep command safe and non-destructive. Output JSON only.\n"
            f"Goal: {goal}\n"
            f"System awareness (pre-plan scan): {json.dumps(system_snapshot, ensure_ascii=True)}\n"
            f"Optimized strategy: {optimized_strategy}\n"
            f"Learned patterns to follow: {json.dumps(learning.get('learned_rules', []), ensure_ascii=True)}\n"
            f"Known successful strategies: {json.dumps(learning.get('success_patterns', [])[:5], ensure_ascii=True)}\n"
            f"Real-time context: {json.dumps(context, ensure_ascii=True)}\n"
            f"Recent failures to avoid repeating: {json.dumps(failures[-5:], ensure_ascii=True)}\n"
            f"{past_line}"
            f"{knowledge_line}"
            "Rules: only safe non-destructive commands from common diagnostics; no markdown; no prose.\n"
            "Decision engine rule: If soil_moisture is below 0.30 and mode allows, you may add a device step "
            "with action irrigation_on and explicit safe threshold criteria."
        )
        plan = self._build_plan_from_contract(prompt, goal)
        if not plan.get("requires_human_intervention"):
            plan["strategy"] = optimized_strategy
            plan["confidence"] = self._compute_confidence(learning)
        return self._apply_learning_constraints(plan, learning)

    def decompose(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        hierarchical = self._hierarchical_decompose(plan)
        if hierarchical:
            return self._order_steps_by_deps_and_priority(hierarchical)
        steps = plan.get("steps", [])
        cleaned: list[dict[str, Any]] = []
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("type"), str) and "id" in step:
                cleaned.append(self._normalize_step(step))
        return self._order_steps_by_deps_and_priority(cleaned)

    def _hierarchical_decompose(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        goal_text = str(plan.get("goal", "")).lower()
        if not goal_text:
            return []
        trigger_keywords = {"project report", "feasibility", "dpr", "jaggery plant", "business report"}
        if not any(k in goal_text for k in trigger_keywords):
            return []

        bus = MessageBus()
        researcher = ResearcherAgent(bus)
        coder = CoderAgent(bus)
        reviewer = ReviewerAgent(bus)

        chain = [
            {
                "id": 1,
                "type": "research",
                "description": "Check local knowledge base first for domain baselines; fallback to web only if missing.",
                "command": "",
                "depends_on": [],
                "priority": 1,
                "search_required": True,
                "search_query": f"{str(plan.get('goal', '')).strip()} latest market technical financial data",
                "knowledge_required": True,
                "capabilities": ["search_tool", "knowledge_retrieval"],
            },
            {
                "id": 2,
                "type": "research",
                "description": "Synthesize local knowledge snippets and web evidence into structured research notes.",
                "command": "",
                "depends_on": [1],
                "priority": 1,
                "capabilities": ["search_tool", "knowledge_retrieval"],
            },
            {
                "id": 3,
                "type": "coding",
                "description": "Draft structured project report sections using researcher handoff data.",
                "command": "",
                "depends_on": [2],
                "priority": 2,
            },
            {
                "id": 4,
                "type": "analysis",
                "description": "Review report completeness, consistency, and risk assumptions.",
                "command": "",
                "depends_on": [3],
                "priority": 1,
            },
        ]
        assigned = [
            researcher.assign(chain[0]),
            researcher.assign(chain[1]),
            coder.assign(chain[2]),
            reviewer.assign(chain[3]),
        ]
        return [self._normalize_step(step, idx + 1) for idx, step in enumerate(assigned)]

    def _order_steps_by_deps_and_priority(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Topological order by depends_on; tie-break lower priority number first."""
        if not steps:
            return []
        id_set = {int(s["id"]) for s in steps}
        children: dict[int, list[int]] = {}
        indeg: dict[int, int] = {int(s["id"]): 0 for s in steps}
        for s in steps:
            sid = int(s["id"])
            for d in s.get("depends_on") or []:
                try:
                    di = int(d)
                except (TypeError, ValueError):
                    continue
                if di not in id_set or di == sid:
                    continue
                children.setdefault(di, []).append(sid)
                indeg[sid] = indeg.get(sid, 0) + 1

        ordered: list[dict[str, Any]] = []
        done: set[int] = set()
        pool = [s for s in steps if indeg[int(s["id"])] == 0]
        pool.sort(key=lambda x: (int(x.get("priority", 3)), int(x["id"])))

        while pool:
            s = pool.pop(0)
            sid = int(s["id"])
            if sid in done:
                continue
            done.add(sid)
            ordered.append(s)
            for ch in children.get(sid, []):
                indeg[ch] -= 1
                if indeg[ch] == 0:
                    nxt = next((x for x in steps if int(x["id"]) == ch), None)
                    if nxt and int(nxt["id"]) not in done:
                        pool.append(nxt)
                        pool.sort(key=lambda x: (int(x.get("priority", 3)), int(x["id"])))
        if len(ordered) < len(steps):
            rest = [s for s in steps if int(s["id"]) not in done]
            rest.sort(key=lambda x: (int(x.get("priority", 3)), int(x["id"])))
            ordered.extend(rest)
        return ordered

    def replan(
        self,
        goal: str,
        failed_step: dict[str, Any],
        failure_type: str,
        result: dict[str, Any],
        past_failures: list[dict[str, Any]] | None = None,
        learning_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        failures = past_failures or []
        learning = learning_snapshot or {"failures": [], "success_patterns": [], "learned_rules": []}
        system_snapshot = system_scan_compact()
        optimized_strategy = self.optimize_strategy(goal, learning)
        prompt = (
            "You are a replanning engine for autonomous execution.\n"
            "Create a NEW plan adapted to this failure; do not repeat failing command unchanged.\n"
            "Return only strict JSON in this schema:\n"
            '{"goal":"string","total_steps":1,"steps":[{"id":1,"task_type":"audit|analysis|coding|research|fix|api|device","description":"string","command":"string","depends_on":[1]}]}\n'
            f"Goal: {goal}\n"
            f"System awareness (pre-plan scan): {json.dumps(system_snapshot, ensure_ascii=True)}\n"
            f"Optimized strategy: {optimized_strategy}\n"
            f"Failed step: {json.dumps(failed_step, ensure_ascii=True)}\n"
            f"Failure type: {failure_type}\n"
            f"Failure result: {json.dumps(result, ensure_ascii=True)}\n"
            f"Learned patterns to follow: {json.dumps(learning.get('learned_rules', []), ensure_ascii=True)}\n"
            f"Recent failures: {json.dumps(failures[-8:], ensure_ascii=True)}\n"
            "Examples: if docker not found, add diagnostic checks and fallback using git/python commands."
        )
        plan = self._build_plan_from_contract(prompt, goal, failed_step=failed_step)
        if not plan.get("requires_human_intervention"):
            plan["strategy"] = optimized_strategy
            plan["confidence"] = self._compute_confidence(learning)
        return self._apply_learning_constraints(plan, learning)

    def _build_plan_from_contract(
        self,
        prompt: str,
        goal: str,
        failed_step: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            plan_model = call_llm_structured(PlanModel, prompt)
        except Exception:
            # Safe fallback: fail closed and require operator intervention instead of accepting raw LLM text.
            return self._safe_human_intervention_plan(goal)
        if not plan_model.steps:
            return self._fallback_plan(goal, failed_step=failed_step)
        return self._contract_plan_to_internal(plan_model, goal)

    def _contract_plan_to_internal(self, plan_model: PlanModel, goal: str) -> dict[str, Any]:
        normalized_steps = []
        for idx, step_model in enumerate(plan_model.steps, start=1):
            normalized_steps.append(self._normalize_step_from_contract(step_model, idx))
        if not normalized_steps:
            return self._fallback_plan(goal)
        return {
            "goal": str(plan_model.goal).strip() or goal,
            "total_steps": int(plan_model.total_steps or len(normalized_steps)),
            "steps": normalized_steps,
        }

    def _normalize_step_from_contract(self, step: StepModel, default_id: int = 1) -> dict[str, Any]:
        return self._normalize_step(
            {
                "id": int(step.id or default_id),
                "type": str(step.task_type),
                "description": str(step.description),
                "command": str(step.command or ""),
                "depends_on": list(step.depends_on),
            },
            default_id=default_id,
        )

    def _normalize_step(self, step: dict[str, Any], default_id: int = 1) -> dict[str, Any]:
        step_type = str(step.get("type", "analysis")).lower()
        retry_limit = int(step.get("retry_limit", 2))
        pri_raw = step.get("priority", 3)
        try:
            priority = max(1, min(int(pri_raw), 5))
        except (TypeError, ValueError):
            priority = 3
        deps_raw = step.get("depends_on") or []
        depends_on: list[int] = []
        if isinstance(deps_raw, list):
            for d in deps_raw:
                try:
                    depends_on.append(int(d))
                except (TypeError, ValueError):
                    continue
        tier_raw = str(step.get("tier", "normal")).strip().lower()
        if tier_raw not in {"critical", "normal", "optional"}:
            tier_raw = "normal"
        risk_raw = str(step.get("risk_level", "low")).strip().lower()
        if risk_raw not in {"low", "medium", "high"}:
            risk_raw = "low"
        parallel_raw = step.get("parallel_safe", False)
        parallel_safe = parallel_raw is True or str(parallel_raw).lower() in {"1", "true", "yes"}
        if step_type != "audit" or not str(step.get("command", "")).strip():
            parallel_safe = False
        normalized = {
            "id": int(step.get("id", default_id)),
            "type": step_type,
            "description": str(step.get("description", f"{step_type} task")).strip(),
            "command": str(step.get("command", "")).strip(),
            "expected_output_regex": str(step.get("expected_output_regex", "")).strip(),
            "success_criteria": str(step.get("success_criteria", "Command executes successfully with expected output.")).strip(),
            "retry_limit": max(0, min(retry_limit, 5)),
            "priority": priority,
            "depends_on": depends_on,
            "tier": tier_raw,
            "risk_level": risk_raw,
            "parallel_safe": parallel_safe,
            "status": "pending",
            "retries_used": 0,
            "result_history": [],
        }
        # Preserve hierarchical multi-agent metadata and safe tool capabilities.
        passthrough_keys = (
            "assigned_agent",
            "message_bus_inputs",
            "research_summary",
            "search_results",
            "search_query",
            "search_required",
            "knowledge_required",
            "knowledge_results",
            "knowledge_summary",
            "web_search_used",
            "capabilities",
            "security_monitored",
        )
        for key in passthrough_keys:
            if key in step:
                normalized[key] = step[key]
        return normalized

    def _fallback_plan(self, goal: str, failed_step: dict[str, Any] | None = None) -> dict[str, Any]:
        failure_hint = "Collect environment and repository diagnostics, then analyze failures."
        if failed_step:
            failure_hint = f"Recover from failed step {failed_step.get('id', 'unknown')} using safer diagnostics."
        return {
            "goal": goal,
            "total_steps": 4,
            "strategy": failure_hint,
            "confidence": 0.35,
            "steps": [
                self._normalize_step(
                    {
                        "id": 1,
                        "type": "audit",
                        "description": "Capture execution location",
                        "command": "pwd",
                        "success_criteria": "output contains a valid working directory path",
                        "retry_limit": 1,
                    },
                    1,
                ),
                self._normalize_step(
                    {
                        "id": 2,
                        "type": "audit",
                        "description": "List working directory files",
                        "command": "ls",
                        "success_criteria": "output includes repository files",
                        "retry_limit": 1,
                    },
                    2,
                ),
                self._normalize_step(
                    {
                        "id": 3,
                        "type": "audit",
                        "description": "Inspect repository change state",
                        "command": "git status",
                        "success_criteria": "output includes branch or changes information",
                        "retry_limit": 1,
                    },
                    3,
                ),
                self._normalize_step(
                    {
                        "id": 4,
                        "type": "analysis",
                        "description": "Analyze collected results and propose safe next actions",
                        "command": "",
                        "success_criteria": "analysis summary identifies at least one actionable finding",
                        "retry_limit": 1,
                    },
                    4,
                ),
            ],
        }

    def _safe_human_intervention_plan(self, goal: str) -> dict[str, Any]:
        return {
            "goal": goal,
            "total_steps": 0,
            "strategy": "Structured plan validation failed; human intervention required.",
            "confidence": 0.0,
            "requires_human_intervention": True,
            "steps": [],
        }

    def optimize_strategy(self, goal: str, history: dict[str, Any]) -> str:
        goal_lower = goal.lower()
        failures = history.get("failures", [])
        success_patterns = history.get("success_patterns", [])
        learned_rules = [str(rule).lower() for rule in history.get("learned_rules", [])]

        if any("docker not found" in json.dumps(item).lower() for item in failures):
            return "Avoid docker-dependent commands; prefer filesystem and git diagnostics."
        if any("blocked command" in rule for rule in learned_rules):
            return "Use minimal approved commands and avoid previously blocked patterns."
        if "audit" in goal_lower and success_patterns:
            best = success_patterns[0]
            return f"Prioritize historically successful command path centered on `{best.get('command', 'pwd')}`."
        return "Incremental diagnostics then constrained remediation based on observed outcomes."

    def _compute_confidence(self, history: dict[str, Any]) -> float:
        failures = len(history.get("failures", []))
        successes = len(history.get("success_patterns", []))
        confidence = 0.45 + min(successes * 0.05, 0.35) - min(failures * 0.07, 0.5)
        return round(max(0.1, min(confidence, 0.95)), 2)

    def _apply_learning_constraints(self, plan: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
        failure_patterns = [
            str(item.get("pattern", "")).lower()
            for item in history.get("failures", [])
            if isinstance(item, dict)
        ]
        avoid_docker = any("docker" in pattern and ("repeated" in pattern or "blocked" in pattern) for pattern in failure_patterns)

        if not avoid_docker:
            return plan

        filtered_steps = []
        for step in plan.get("steps", []):
            command = str(step.get("command", "")).lower().strip()
            if command.startswith("docker"):
                continue
            filtered_steps.append(step)

        if not filtered_steps:
            return self._fallback_plan(str(plan.get("goal", "Audit my system and fix issues")))

        print("[STRATEGY IMPROVED]")
        return {**plan, "steps": filtered_steps}
