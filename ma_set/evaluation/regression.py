"""
Regression Evaluator (AgentEval)
================================
Ensures existing baseline functionality remains unbroken after agent edits.
Enforces the 0-regression invariant.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment


class RegressionEvaluationResult:
    def __init__(
        self,
        passed: bool,
        baseline_tests_passed: int,
        regressions_detected: List[str],
        duration_s: float,
    ):
        self.passed = passed
        self.baseline_tests_passed = baseline_tests_passed
        self.regressions_detected = regressions_detected
        self.duration_s = duration_s

    @property
    def score(self) -> float:
        return 100.0 if self.passed else max(0.0, 100.0 - (len(self.regressions_detected) * 40.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 1),
            "baseline_tests_passed": self.baseline_tests_passed,
            "regressions_detected": self.regressions_detected,
            "duration_s": round(self.duration_s, 3),
        }


RegressionCheckResult = RegressionEvaluationResult


class RegressionEvaluator:
    """Verifies that no pre-existing tests were broken by agent changes."""

    def __init__(self, baseline_test_command: str = ".venv/bin/python -m pytest demo_target/tests/ -v -k 'not xfail' || pytest demo_target/tests/ -v -k 'not xfail'"):
        self.baseline_cmd = baseline_test_command

    def evaluate(
        self,
        environment: Any = None,
        workspace_dir: Optional[Any] = None,
    ) -> RegressionEvaluationResult:
        if environment is not None and hasattr(environment, "execute"):
            res = environment.execute(self.baseline_cmd, timeout=30)
            output = res.stdout + "\n" + res.stderr
            exit_code = res.exit_code
            duration = res.duration_s
        elif environment is not None and hasattr(environment, "execute_command"):
            res = environment.execute_command(self.baseline_cmd, timeout=30)
            output = res.stdout + "\n" + res.stderr
            exit_code = res.exit_code
            duration = getattr(res, "duration_s", 1.0)
        elif workspace_dir is not None:
            import subprocess
            import time
            from pathlib import Path
            t0 = time.time()
            proc = subprocess.run(
                self.baseline_cmd,
                shell=True,
                cwd=str(workspace_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = proc.stdout + "\n" + proc.stderr
            exit_code = proc.returncode
            duration = time.time() - t0
        else:
            return RegressionEvaluationResult(
                passed=True,
                baseline_tests_passed=0,
                regressions_detected=[],
                duration_s=0.0,
            )

        regressions: List[str] = []
        passed_count = 0

        # Check for FAILED tests
        for line in output.splitlines():
            if "FAILED " in line:
                regressions.append(line.strip())

        pass_m = re.search(r"(\d+)\s+passed", output)
        if pass_m:
            passed_count = int(pass_m.group(1))

        passed = len(regressions) == 0 and exit_code == 0

        return RegressionEvaluationResult(
            passed=passed,
            baseline_tests_passed=passed_count,
            regressions_detected=regressions,
            duration_s=duration,
        )

