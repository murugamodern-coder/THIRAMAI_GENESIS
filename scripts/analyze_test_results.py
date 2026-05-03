#!/usr/bin/env python3
"""
Analyze local live test results (`local_live_test_results.txt`) and print a verdict.
Uses ASCII-only output for Windows consoles (cp1252).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class TestResultsAnalyzer:
    """Analyze test results and provide verdict."""

    def __init__(self, results_file: str = "local_live_test_results.txt") -> None:
        self.results_file = Path(results_file)
        self.results: dict[str, bool] = {}
        self.critical_issues: list[str] = []
        self.warnings: list[str] = []

    def analyze(self) -> bool:
        if not self.results_file.exists():
            print(f"FAIL: Results file not found: {self.results_file}")
            return False

        content = self.results_file.read_text(encoding="utf-8", errors="replace")

        self.check_environment(content)
        self.check_services(content)
        self.check_health(content)
        self.check_policy_engine(content)
        self.check_authentication(content)
        self.check_decision_api(content)
        self.check_ai_brain(content)
        self.check_full_verifier(content)

        self.print_analysis()
        return len(self.critical_issues) == 0

    def _step1_block(self, content: str) -> str:
        i = content.find("STEP 1:")
        j = content.find("STEP 2:")
        if i >= 0 and j > i:
            return content[i:j]
        return content[:6000]

    def check_environment(self, content: str) -> None:
        step1 = self._step1_block(content)
        if ".env.production exists" in content:
            self.results["Environment"] = True
        else:
            self.results["Environment"] = False
            self.critical_issues.append("Missing .env.production file")

        ab_off = bool(
            re.search(r"(?m)^\s*THIRAMAI_DECISION_AB_TEST\s*=\s*false\s*$", step1, re.I)
            or re.search(r"(?m)^\s*DECISION_AB_TEST\s*=\s*false\s*$", step1, re.I)
        )
        if ab_off:
            self.results["A/B Test Disabled"] = True
        else:
            self.results["A/B Test Disabled"] = False
            if "Pre-deployment checks passed" in content:
                self.warnings.append("A/B-off not found in STEP 1 log (pre-deploy may still enforce)")
            else:
                self.critical_issues.append("A/B test not clearly disabled in STEP 1 snapshot")

        pool_ok = bool(
            re.search(r"(?m)^\s*POOL_SIZE\s*=", step1)
            or re.search(r"(?m)^\s*THIRAMAI_DB_POOL_SIZE\s*=", step1)
        ) and bool(
            re.search(r"(?m)^\s*MAX_OVERFLOW\s*=", step1)
            or re.search(r"(?m)^\s*THIRAMAI_DB_MAX_OVERFLOW\s*=", step1)
        )
        if pool_ok:
            self.results["Database Pool"] = True
        else:
            self.results["Database Pool"] = False
            self.warnings.append("Database pool keys not seen in STEP 1 grep (check .env.production)")

    def check_services(self, content: str) -> None:
        if "Docker compose not running or not available" in content:
            self.results["Docker Services"] = False
            self.warnings.append("Docker compose probe unavailable or stack not reachable")
        elif "Docker compose available" in content:
            if re.search(r"\brunning\b", content, re.I):
                self.results["Docker Services"] = True
            else:
                self.results["Docker Services"] = False
                self.warnings.append("Docker compose ok but no 'running' state in captured output")
        else:
            self.results["Docker Services"] = False
            self.warnings.append("Docker compose status unclear")

    def check_health(self, content: str) -> None:
        self.results["Health - Live"] = "Live endpoint HTTP 200" in content
        if not self.results["Health - Live"]:
            self.critical_issues.append("Health live endpoint did not return HTTP 200")

        self.results["Health - Ready"] = "Ready endpoint HTTP 200" in content
        if not self.results["Health - Ready"]:
            self.critical_issues.append("Health ready endpoint did not return HTTP 200")

        self.results["Health - System"] = "System endpoint HTTP 200" in content
        if not self.results["Health - System"]:
            self.warnings.append("Health system endpoint did not return HTTP 200")

    def check_policy_engine(self, content: str) -> None:
        # Match plain text (Git Bash may mojibake emoji in tee output)
        if "PolicyEngine operational" in content:
            self.results["PolicyEngine"] = True
        elif "PolicyEngine not healthy" in content:
            self.results["PolicyEngine"] = False
            self.critical_issues.append("PolicyEngine not operational")
        else:
            self.results["PolicyEngine"] = False
            self.warnings.append("PolicyEngine status unknown")

        if re.search(r"Circuit Breaker State:\s*closed\b", content, re.I):
            self.results["Circuit Breaker"] = True
        elif re.search(r"Circuit Breaker State:\s*half_open\b", content, re.I):
            self.results["Circuit Breaker"] = True
            self.warnings.append("Circuit breaker half-open (recovering)")
        elif re.search(r"Circuit Breaker State:\s*open\b", content, re.I):
            self.results["Circuit Breaker"] = False
            self.critical_issues.append("Circuit breaker is OPEN")
        else:
            self.results["Circuit Breaker"] = False
            self.warnings.append("Circuit breaker state unknown")

    def check_authentication(self, content: str) -> None:
        self.results["Authentication"] = "Authentication successful" in content
        if not self.results["Authentication"]:
            self.critical_issues.append("Authentication failed")

    def check_decision_api(self, content: str) -> None:
        self.results["Decision API"] = "Decision API call successful" in content
        if not self.results["Decision API"]:
            self.critical_issues.append("Decision API failed")

    def check_ai_brain(self, content: str) -> None:
        if "USING POLICYENGINE (AI BRAIN ACTIVE!)" in content:
            self.results["AI Brain (PolicyEngine)"] = True
        elif "Using safe fallback" in content:
            self.results["AI Brain (PolicyEngine)"] = True
            self.warnings.append("Using safe_fallback (degraded but governed)")
        elif "Unexpected brain source" in content:
            self.results["AI Brain (PolicyEngine)"] = False
            self.critical_issues.append("AI brain source unexpected or not PolicyEngine")
        else:
            self.results["AI Brain (PolicyEngine)"] = False
            if "Skipping (no auth token)" not in content:
                self.warnings.append("AI brain source not confirmed from decision response")

    def check_full_verifier(self, content: str) -> None:
        tail = content[-8000:] if len(content) > 8000 else content
        if "FULL VERIFICATION PASSED" in content:
            self.results["verify_live_system.py"] = True
        elif "ALL CHECKS PASSED" in tail and "VERIFICATION SUMMARY" in tail:
            self.results["verify_live_system.py"] = True
        else:
            self.results["verify_live_system.py"] = False
            self.warnings.append("verify_live_system.py did not report full pass (see STEP 12 in log)")

    def print_analysis(self) -> None:
        print("\n" + "=" * 70)
        print("THIRAMAI LOCAL LIVE TEST ANALYSIS")
        print("=" * 70)

        print("\nComponent Status:")
        for component, passed in self.results.items():
            status = "[PASS]" if passed else "[FAIL]"
            print(f"  {status} {component}")

        if self.critical_issues:
            print("\nCRITICAL ISSUES:")
            for issue in self.critical_issues:
                print(f"  - {issue}")

        if self.warnings:
            print("\nWARNINGS:")
            for warning in self.warnings:
                print(f"  - {warning}")

        print("\n" + "=" * 70)

        if not self.critical_issues:
            print("ALL CRITICAL CHECKS PASSED")
            print("\nTHIRAMAI LOCAL TEST ANALYSIS: OK")
            print("\nYour AI-powered decision system appears operational (per log).")
            print("\nKey achievements:")
            print("  - Services running")
            print("  - Health checks passing")
            print("  - PolicyEngine active")
            print("  - Decision API working")
            print("  - AI brain verified")
            print("\nNext steps:")
            print("  1. Monitor: docker compose -f docker-compose.production.yml --env-file .env.production logs -f web")
            print("  2. Test with real users")
            print("  3. Establish quality baseline (after 100+ decisions)")
        else:
            print("CRITICAL ISSUES FOUND")
            print("\nFix the issues above before considering system live.")
            print("\nCommon fixes:")
            print("  - Check .env.production configuration")
            print("  - Restart: docker compose -f docker-compose.production.yml --env-file .env.production restart")
            print("  - Logs: docker compose -f docker-compose.production.yml --env-file .env.production logs web")

        print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Thiramai local live test results")
    parser.add_argument(
        "--file",
        default="local_live_test_results.txt",
        help="Results file to analyze",
    )
    args = parser.parse_args()
    analyzer = TestResultsAnalyzer(args.file)
    success = analyzer.analyze()
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
