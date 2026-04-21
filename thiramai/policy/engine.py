from __future__ import annotations

from thiramai.policy.loader import PolicyRuleLoader
from thiramai.policy.models import ExecutionContext, PolicyDecision
from thiramai.policy.parser import CommandParser


class PolicyEngine:
    def __init__(self, *, allow_high_risk: bool = False) -> None:
        self.allow_high_risk = bool(allow_high_risk)
        self.parser = CommandParser()
        self.loader = PolicyRuleLoader()

    def evaluate(self, command_parts: list[str], context: ExecutionContext) -> PolicyDecision:
        if not command_parts:
            return PolicyDecision(allow=False, reason="Empty command_parts.", policy_id="baseline.v1.empty")

        try:
            ast = self.parser.parse(command_parts)
        except Exception as exc:
            return PolicyDecision(
                allow=False,
                reason=f"Command parse failed; denied by fail-safe policy ({exc}).",
                policy_id="ast.v1.parse_failed",
            )

        if ast.has_pipes or ast.has_redirection or ast.has_chaining:
            return PolicyDecision(
                allow=False,
                reason="Pipes, redirection, or command chaining is not permitted.",
                policy_id="ast.v1.metachar_denied",
            )

        if context.risk_level == "high" and not self.allow_high_risk:
            return PolicyDecision(
                allow=False,
                reason="High-risk task execution is disabled by policy.",
                policy_id="baseline.v1.high_risk_denied",
            )

        rules = self.loader.load()
        command_rule = rules.commands.get(ast.binary)
        if command_rule is None:
            return PolicyDecision(
                allow=False,
                reason=f"Base command `{ast.binary}` is not approved by baseline policy.",
                policy_id="rules.v1.base_command_denied",
            )

        denied_sub = {x.lower() for x in command_rule.denied_sub_commands}
        if ast.sub_command and ast.sub_command in denied_sub:
            return PolicyDecision(
                allow=False,
                reason=f"Sub-command `{ast.sub_command}` is denied by policy.",
                policy_id="rules.v1.sub_command_denied",
            )

        allowed_sub = [x.lower() for x in command_rule.allowed_sub_commands]
        allowed_by_task = [x.lower() for x in command_rule.allowed_sub_commands_by_task.get(context.task_type, [])]
        effective_allowed = allowed_by_task if allowed_by_task else allowed_sub
        if ast.sub_command:
            if not command_rule.allow_any_sub_command and effective_allowed and ast.sub_command not in effective_allowed:
                return PolicyDecision(
                    allow=False,
                    reason=f"Sub-command `{ast.sub_command}` is not allowed for task `{context.task_type}`.",
                    policy_id="rules.v1.sub_command_not_allowed",
                )
        elif not command_rule.allow_without_sub_command and not command_rule.allow_any_sub_command:
            return PolicyDecision(
                allow=False,
                reason="Sub-command is required by policy for this command.",
                policy_id="rules.v1.sub_command_required",
            )

        denied_flags = {x.lower() for x in command_rule.denied_flags}
        for flg in ast.flags:
            if flg in denied_flags:
                return PolicyDecision(
                    allow=False,
                    reason=f"Flag `{flg}` is denied by policy.",
                    policy_id="rules.v1.flag_denied",
                )

        allowed_flags = {x.lower() for x in command_rule.allowed_flags}
        if allowed_flags:
            for flg in ast.flags:
                if flg not in allowed_flags:
                    return PolicyDecision(
                        allow=False,
                        reason=f"Flag `{flg}` is not in allowed flag set.",
                        policy_id="rules.v1.flag_not_allowed",
                    )

        return PolicyDecision(
            allow=True,
            reason="Command approved by AST parser and declarative rule policy.",
            policy_id="rules.v1.allow",
        )
