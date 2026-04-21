from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CommandRule(BaseModel):
    allowed_sub_commands: list[str] = Field(default_factory=list)
    allowed_sub_commands_by_task: dict[str, list[str]] = Field(default_factory=dict)
    denied_sub_commands: list[str] = Field(default_factory=list)
    allowed_flags: list[str] = Field(default_factory=list)
    denied_flags: list[str] = Field(default_factory=list)
    allow_without_sub_command: bool = True
    allow_any_sub_command: bool = False


class PolicyRules(BaseModel):
    version: str = "1"
    commands: dict[str, CommandRule] = Field(default_factory=dict)


class PolicyRuleLoader:
    def __init__(self, rule_path: Path | None = None) -> None:
        default_path = Path(__file__).resolve().parent / "rules" / "default.json"
        self.rule_path = rule_path or default_path

    def load(self) -> PolicyRules:
        payload = self._read_payload(self.rule_path)
        try:
            return PolicyRules.model_validate(payload)
        except Exception:
            return PolicyRules()

    def _read_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"version": "1", "commands": {}}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"version": "1", "commands": {}}
        suffix = path.suffix.lower()
        if suffix == ".json":
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"version": "1", "commands": {}}
        if suffix in {".yml", ".yaml"}:
            try:
                import yaml

                parsed = yaml.safe_load(raw)
                return parsed if isinstance(parsed, dict) else {"version": "1", "commands": {}}
            except Exception:
                return {"version": "1", "commands": {}}
        return {"version": "1", "commands": {}}
