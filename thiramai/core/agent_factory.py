from thiramai.agents.analysis_agent import AnalysisAgent
from thiramai.agents.api_agent import APIAgent
from thiramai.agents.audit_agent import AuditAgent
from thiramai.agents.coding_agent import CodingAgent
from thiramai.agents.research_agent import ResearchAgent
from thiramai.core.agent_generator import AgentGenerator


class AgentFactory:
    def __init__(self) -> None:
        self.generator = AgentGenerator()
        self._agents = {
            "audit": AuditAgent(),
            "research": ResearchAgent(),
            "analysis": AnalysisAgent(),
            "coding": CodingAgent(),
            "fix": CodingAgent(),
            "api": APIAgent(),
        }

    def create_agent(self, task: dict) -> object:
        task_type = str(task.get("type", "analysis")).lower()
        generated = self.generator.get_best_agent_for_type(task_type)
        if generated:
            try:
                instance = self.generator.load_generated_agent(
                    module_name=str(generated["module"]),
                    class_name=str(generated["agent_name"]),
                )
                self.generator.increment_usage(str(generated["agent_name"]))
                return instance
            except Exception:
                pass
        return self._agents.get(task_type, AnalysisAgent())

    def detect_capability_gap(
        self,
        task: dict,
        result: dict,
        review: dict,
    ) -> dict | None:
        return self.generator.detect_capability_gap(task, result, review)

    def expand_capability(self, agent_type: str, purpose: str) -> dict:
        generated = self.generator.generate_agent(agent_type=agent_type, purpose=purpose)
        print("[NEW AGENT CREATED]")
        print(
            {
                "agent_name": generated["agent_name"],
                "module": generated["module"],
                "path": generated["path"],
            }
        )
        print("[CAPABILITY EXPANDED]")
        return generated
