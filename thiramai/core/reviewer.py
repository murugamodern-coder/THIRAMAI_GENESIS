import json
import re
from typing import Any

from thiramai.config import (
    THIRAMAI_REVIEW_DOUBLE_CHECK,
    THIRAMAI_REVIEW_MIN_CONFIDENCE,
    get_thiramai_mode,
)
from pydantic import BaseModel

from thiramai.integrations.llm_clients import call_llm_structured
from thiramai.schemas.contracts import ReviewModel


class Reviewer:
    FAILURE_TYPES = {"execution_error", "blocked_command", "timeout", "invalid_output"}

    def review(self, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        failure_type = self._classify_failure_type(result)
        criteria_status, criteria_reason = self._validate_success_criteria(task, result)
        suspicious = self._heuristic_suspicious(task, result, criteria_status)

        prompt = (
            "You are an autonomous QA reviewer that must judge execution quality.\n"
            "Return strict JSON only:\n"
            '{"status":"pass|fail","reason":"short reason","suggested_fix":"optional safe command",'
            '"confidence":0.0}\n'
            "confidence is 0..1 (higher = more certain that pass is correct).\n"
            f"Task:\n{json.dumps(task, ensure_ascii=True)}\n"
            f"Result:\n{json.dumps(result, ensure_ascii=True)}\n"
            f"Deterministic check outcome: {criteria_status} ({criteria_reason})\n"
            f"Heuristic suspicious={suspicious}\n"
            "Fix command must be safe and non-destructive and should adapt to failure cause."
        )
        parsed = self._structured_review_or_fallback(prompt)
        llm_status = parsed.status
        confidence = max(0.0, min(1.0, float(parsed.confidence)))

        if criteria_status == "pass" and llm_status == "pass":
            status = "pass"
        else:
            status = "fail"

        reason = str(parsed.reason)
        combined_reason = f"{criteria_reason}; reviewer={reason}; failure_type={failure_type}"
        fix = str(parsed.suggested_fix).strip()

        verification_note = ""
        if (
            status == "pass"
            and THIRAMAI_REVIEW_DOUBLE_CHECK
            and get_thiramai_mode() != "dry-run"
            and (confidence < 0.82 or suspicious)
        ):
            ok_v, vconf, verification_note = self._verify_with_llm(task, result)
            confidence = min(confidence, vconf)
            if not ok_v:
                status = "fail"
                combined_reason += f"; verification_failed: {verification_note}"

        if status == "pass" and confidence < THIRAMAI_REVIEW_MIN_CONFIDENCE:
            status = "fail"
            combined_reason += f"; below_min_confidence({confidence:.2f}<{THIRAMAI_REVIEW_MIN_CONFIDENCE:.2f})"

        out: dict[str, Any] = {
            "status": status,
            "reason": combined_reason,
            "fix": fix,
            "suggested_fix": fix,
            "failure_type": failure_type,
            "criteria_status": criteria_status,
            "confidence": confidence,
            "verification_note": verification_note,
            "suspicious": suspicious,
        }
        return out

    def _verify_with_llm(self, task: dict[str, Any], result: dict[str, Any]) -> tuple[bool, float, str]:
        class VerifyModel(BaseModel):
            verified: bool
            confidence: float
            note: str = ""

        prompt = (
            "Verify whether this command result satisfies the task intent for a production autonomous agent.\n"
            "Return strict JSON only: {\"verified\":true|false,\"confidence\":0.0,\"note\":\"short\"}\n"
            f"Task:\n{json.dumps(task, ensure_ascii=True)}\n"
            f"Result:\n{json.dumps(result, ensure_ascii=True)}\n"
            "Be conservative: if unsure, verified=false."
        )
        try:
            data = call_llm_structured(VerifyModel, prompt)
            verified = bool(data.verified)
            conf = float(data.confidence)
            conf = max(0.0, min(1.0, conf))
            note = str(data.note).strip()
            return verified, conf, note
        except Exception as exc:  # noqa: BLE001
            return False, 0.35, f"verify_parse_error:{exc}"

    def _heuristic_suspicious(self, task: dict[str, Any], result: dict[str, Any], criteria_status: str) -> bool:
        out = str(result.get("output", "") or result.get("stdout", ""))
        cmd = str(task.get("command", ""))
        if criteria_status == "pass" and len(out.strip()) < 2 and "git" in cmd.lower():
            return True
        if str(result.get("status", "")).lower() == "success" and not out.strip() and "contains" in str(
            task.get("success_criteria", "")
        ).lower():
            return True
        return False

    def _structured_review_or_fallback(self, prompt: str) -> ReviewModel:
        try:
            return call_llm_structured(ReviewModel, prompt)
        except Exception as exc:
            # Safe fallback: fail closed and require human verification.
            return ReviewModel(
                status="fail",
                confidence=0.0,
                reason=f"Structured reviewer validation failed: {exc}",
                suggested_fix="",
            )

    def _classify_failure_type(self, result: dict[str, Any]) -> str:
        status = str(result.get("status", "")).lower()
        if status == "blocked":
            return "blocked_command"
        if status == "timeout":
            return "timeout"
        if status == "error":
            return "execution_error"
        return "invalid_output"

    def _validate_success_criteria(self, task: dict[str, Any], result: dict[str, Any]) -> tuple[str, str]:
        if str(result.get("status", "")).lower() != "success":
            return "fail", f"Execution status is {result.get('status', 'unknown')}"

        criteria = str(task.get("success_criteria", "")).strip().lower()
        output = str(result.get("output", "") or result.get("stdout", "")).strip()
        expected_re = str(task.get("expected_output_regex", "")).strip()
        if expected_re:
            try:
                if re.search(expected_re, output, re.DOTALL | re.IGNORECASE):
                    return "pass", "expected_output_regex matched"
                return "fail", "expected_output_regex did not match"
            except re.error:
                return "fail", "invalid expected_output_regex on task"

        if not criteria:
            return "pass", "No explicit success criteria provided"

        if "should return running containers" in criteria:
            if "container" in output.lower() or "image" in output.lower():
                return "pass", "Docker listing output pattern matched"
            return "fail", "Docker output does not indicate container listing"

        if "contains" in criteria:
            marker = criteria.split("contains", 1)[1].strip().strip(".")
            if marker and marker in output.lower():
                return "pass", f"Output contains expected marker: {marker}"
            return "fail", f"Output missing expected marker: {marker}"

        if "valid working directory path" in criteria:
            if output and ("/" in output or "\\" in output):
                return "pass", "Detected directory-like output"
            return "fail", "Output does not look like a path"

        if "branch" in criteria or "changes information" in criteria:
            lower_output = output.lower()
            if "on branch" in lower_output or "changes not staged" in lower_output or "nothing to commit" in lower_output:
                return "pass", "Git status output matched expected indicators"
            return "fail", "Git status indicators not found"

        if output:
            return "pass", "Command succeeded with non-empty output"
        return "fail", "Output is empty and criteria not satisfied"
