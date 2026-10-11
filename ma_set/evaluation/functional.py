"""
Functional Evaluator (AgentEval)
================================
Performs deterministic evaluation of functional correctness by executing tests
inside the isolated environment and analyzing test outcomes.
Rule: Never use an LLM for deterministic facts like test pass/fail.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment


from dataclasses import dataclass, field


@dataclass
class TestCaseFailure:
    test_name: str
    message: str


class FunctionalEvaluationResult:
    def __init__(
        self,
        passed: bool,
        tests_total: int,
        tests_passed: int,
        tests_failed: int,
        tests_xfailed: int,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_s: float,
        error_message: Optional[str] = None,
        failures: Optional[List[TestCaseFailure]] = None,
    ):
        self.passed = passed
        self.success = passed
        self.tests_total = tests_total
        self.tests_passed = tests_passed
        self.tests_failed = tests_failed
        self.failed_count = tests_failed
        self.tests_xfailed = tests_xfailed
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration_s = duration_s
        self.error_message = error_message
        self.failures = failures or []

    @property
    def pass_ratio(self) -> float:
        if self.tests_total == 0:
            return 1.0 if self.passed else 0.0
        return self.tests_passed / self.tests_total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "success": self.success,
            "tests_total": self.tests_total,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_xfailed": self.tests_xfailed,
            "exit_code": self.exit_code,
            "pass_ratio": round(self.pass_ratio, 3),
            "duration_s": round(self.duration_s, 3),
            "error_message": self.error_message,
            "failures": [{"test_name": f.test_name, "message": f.message} for f in self.failures],
        }


class FunctionalEvaluator:
    """Executes and grades functional test suites deterministically."""

    def __init__(self, test_command: Optional[str] = None):
        import sys
        self.test_command = test_command or f"{sys.executable} -m pytest demo_target/tests/ -v -k 'not xfail'"

    def evaluate(
        self,
        environment: Any = None,
        custom_test_cmd: Optional[str] = None,
        workspace_dir: Optional[Any] = None,
        test_commands: Optional[List[str]] = None,
    ) -> FunctionalEvaluationResult:
        import sys
        raw_cmd = custom_test_cmd or (test_commands[0] if test_commands else None) or self.test_command
        if raw_cmd and not raw_cmd.startswith("pytest") and not raw_cmd.startswith(sys.executable):
            if Path(raw_cmd).suffix == ".py" or "/" in raw_cmd:
                cmd = f"{sys.executable} -m pytest demo_target/tests/ -v -k 'not xfail'"
            else:
                cmd = f"{sys.executable} -m pytest {raw_cmd}"
        else:
            cmd = raw_cmd

        stdout = ""
        stderr = ""
        exit_code = 0
        duration_s = 0.0
        timed_out = False

        if environment is not None and hasattr(environment, "execute"):
            res = environment.execute(cmd, timeout=30)
            stdout = res.stdout
            stderr = res.stderr
            exit_code = res.exit_code
            duration_s = res.duration_s
            timed_out = res.timed_out
        elif environment is not None and hasattr(environment, "execute_command"):
            res = environment.execute_command(cmd, timeout=30)
            stdout = res.stdout
            stderr = res.stderr
            exit_code = res.exit_code
            duration_s = getattr(res, "duration_s", 1.0)
            timed_out = getattr(res, "timed_out", False)
        elif workspace_dir is not None:
            import subprocess
            import time
            t0 = time.time()
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(workspace_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
            duration_s = time.time() - t0

        output = stdout + "\n" + stderr
        passed_count = 0
        failed_count = 0
        xfailed_count = 0
        failures: List[TestCaseFailure] = []

        pass_m = re.search(r"(\d+)\s+passed", output)
        fail_m = re.search(r"(\d+)\s+failed", output)
        xfail_m = re.search(r"(\d+)\s+xfailed", output)

        if pass_m:
            passed_count = int(pass_m.group(1))
        if fail_m:
            failed_count = int(fail_m.group(1))
        if xfail_m:
            xfailed_count = int(xfail_m.group(1))

        # Parse specific FAILED test lines
        for line in output.splitlines():
            if line.startswith("FAILED ") or " FAILED " in line:
                parts = line.split("FAILED")
                tname = parts[-1].strip().split()[0] if parts[-1].strip() else line
                failures.append(TestCaseFailure(test_name=tname, message=line.strip()))

        tests_total = passed_count + failed_count + xfailed_count
        is_success = (exit_code == 0) and (failed_count == 0)

        err_msg = None
        if not is_success:
            if failed_count > 0:
                err_msg = f"{failed_count} tests failed in execution"
            elif timed_out:
                err_msg = "Test execution timed out"
            else:
                err_msg = f"Non-zero exit code ({exit_code})"

        return FunctionalEvaluationResult(
            passed=is_success,
            tests_total=tests_total,
            tests_passed=passed_count,
            tests_failed=failed_count,
            tests_xfailed=xfailed_count,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration_s,
            error_message=err_msg,
            failures=failures,
        )

