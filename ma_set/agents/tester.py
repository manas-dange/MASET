"""
P1.4 — Tester Agent
=====================
Runs the test suite and linter inside the sandbox and produces a structured
test result and defect list that the orchestrator can feed back to the
Developer agent (FB1 loop).

Workflow
--------
1. Create a Sandbox from the project root.
2. Copy the patched files (from DeveloperResult) into the sandbox.
3. Run  pytest <test_path> -v --tb=short  inside the sandbox.
4. Optionally run  ruff check <src_path>  for linting.
5. Parse results → TesterResult.
6. Emit events throughout.

Events emitted (P1.6)
---------------------
  AGENT_STARTED
  SANDBOX_COMMAND  (from Sandbox)
  SANDBOX_RESULT   (from Sandbox)
  TEST_RESULTS
  AGENT_FINISHED
  AGENT_ESCALATED
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.protection.sandbox import Sandbox


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TesterResult:
    __test__ = False                 # Tell pytest this is not a test suite class
    success: bool                    # True = all tests pass AND no lint errors
    tests_total: int
    tests_passed: int
    tests_failed: int
    tests_xfailed: int
    defect_list: List[str]           # Human-readable defect descriptions
    lint_errors: List[str]
    raw_pytest_output: str
    raw_lint_output: str
    error: str = ""

    @property
    def all_clear(self) -> bool:
        """True when tests pass and no lint errors exist."""
        return self.success and not self.lint_errors


# ---------------------------------------------------------------------------
# Tester Agent
# ---------------------------------------------------------------------------

class TesterAgent:
    __test__ = False

    """
    Runs pytest and ruff inside a disposable sandbox and produces a
    structured TesterResult with a defect list for the FB1 retry loop.

    Parameters
    ----------
    project_root : Path
        Project root (the sandbox copies the whole tree from here).
    test_path : str
        Path to tests, relative to project root (e.g. "demo_target/tests").
    src_path : str
        Path to source code to lint (e.g. "demo_target/app.py").
    run_lint : bool
        Whether to run ruff after pytest (default True).
    event_callback : callable, optional
        Receives event dicts.
    node : str
        IDEF0 node tag (always "A4").
    """

    def __init__(
        self,
        project_root: Path = Path("."),
        test_path: str = "demo_target/tests",
        src_path: str = "demo_target/app.py",
        run_lint: bool = True,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A4",
        agent: str = "tester",
    ):
        self._root = project_root.resolve()
        self._test_path = test_path
        self._src_path = src_path
        self._run_lint = run_lint
        self._cb = event_callback
        self._node = node
        self._agent = agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        run_id: str,
        patched_files: Optional[Dict[str, str]] = None,
        patched_contents: Optional[Dict[str, str]] = None,
    ) -> TesterResult:
        """
        Execute tests (and optionally lint) in a sandbox.

        Parameters
        ----------
        run_id : str
            Current pipeline run ID.
        patched_files : dict, optional
            ``{relative_path: new_content}`` from the Developer agent.
            These are written into the sandbox before tests run.
        """
        self._emit(run_id, "agent_started", {"test_path": self._test_path})

        try:
            patches = patched_files or patched_contents or {}
            result = self._run_in_sandbox(run_id, patches)
        except Exception as exc:
            self._emit(run_id, "agent_escalated", {"error": str(exc)})
            return TesterResult(
                success=False, tests_total=0, tests_passed=0,
                tests_failed=0, tests_xfailed=0,
                defect_list=[str(exc)], lint_errors=[],
                raw_pytest_output="", raw_lint_output="",
                error=str(exc),
            )

        self._emit(run_id, "test_results", {
            "total": result.tests_total,
            "passed": result.tests_passed,
            "failed": result.tests_failed,
            "xfailed": result.tests_xfailed,
            "defects": len(result.defect_list),
            "lint_errors": len(result.lint_errors),
            "success": result.success,
        })
        self._emit(run_id, "agent_finished", {"success": result.success})
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_in_sandbox(
        self, run_id: str, patched_files: Dict[str, str]
    ) -> TesterResult:
        cb = self._make_sandbox_cb(run_id)
        with Sandbox(
            source_dir=self._root,
            run_id=run_id,
            python_executable=sys.executable,
            event_callback=cb,
            node=self._node,
            agent=self._agent,
        ) as sb:
            # Apply patches
            for rel_path, content in patched_files.items():
                sb.apply_patch(rel_path, content)

            # Run pytest — pass the test path that exists inside the sandbox
            sandbox_test_path = str(sb.work_dir / self._test_path)
            pytest_result = sb.run([
                "pytest",
                sandbox_test_path,
                "-v", "--tb=short", "-q",
                "--import-mode=importlib",
            ], extra_env={"PYTHONPATH": str(sb.work_dir)})

            # Optionally run ruff
            lint_output = ""
            lint_errors: List[str] = []
            if self._run_lint:
                sandbox_src = str(sb.work_dir / self._src_path)
                ruff_result = sb.run(["ruff", "check", sandbox_src])
                if ruff_result.exit_code == -1 and "No such file" in ruff_result.stderr:
                    # ruff not installed — skip gracefully
                    lint_output = ""
                else:
                    lint_output = ruff_result.stdout + ruff_result.stderr
                lint_errors = self._parse_lint(lint_output)

        # Parse pytest output
        stats = self._parse_pytest_stats(pytest_result.stdout + pytest_result.stderr)
        defects = self._parse_pytest_defects(pytest_result.stdout + pytest_result.stderr)

        success = (pytest_result.exit_code == 0)

        return TesterResult(
            success=success,
            tests_total=stats["total"],
            tests_passed=stats["passed"],
            tests_failed=stats["failed"],
            tests_xfailed=stats["xfailed"],
            defect_list=defects,
            lint_errors=lint_errors,
            raw_pytest_output=pytest_result.stdout + pytest_result.stderr,
            raw_lint_output=lint_output,
        )

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pytest_stats(output: str) -> Dict[str, int]:
        """Extract passed/failed/xfailed counts from pytest output."""
        stats = {"total": 0, "passed": 0, "failed": 0, "xfailed": 0}
        # Match lines like:  "19 passed, 3 xfailed"  or "2 failed, 17 passed"
        pattern = re.compile(r'(\d+)\s+(passed|failed|xfailed|error)')
        for match in pattern.finditer(output):
            count, kind = int(match.group(1)), match.group(2)
            if kind == "passed":
                stats["passed"] = count
            elif kind == "failed":
                stats["failed"] = count
            elif kind == "xfailed":
                stats["xfailed"] = count
        stats["total"] = stats["passed"] + stats["failed"] + stats["xfailed"]
        return stats

    @staticmethod
    def _parse_pytest_defects(output: str) -> List[str]:
        """
        Extract individual FAILED test lines and error messages.
        Returns a list of strings like:
          "FAILED demo_target/tests/test_app.py::TestSignup::test_signup_missing_email_returns_400"
        """
        defects: List[str] = []
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("FAILED "):
                defects.append(stripped)
            elif stripped.startswith("ERROR ") and "test_" in stripped:
                defects.append(stripped)
            elif "ImportError" in stripped or "ModuleNotFoundError" in stripped:
                defects.append(stripped[:200])
            elif "AssertionError" in stripped:
                defects.append(stripped[:200])
        return defects[:20]   # cap at 20

    @staticmethod
    def _parse_lint(output: str) -> List[str]:
        """Extract ruff error lines."""
        errors = []
        for line in output.splitlines():
            if re.match(r'.+:\d+:\d+:', line):
                errors.append(line.strip()[:200])
        return errors[:20]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_sandbox_cb(self, run_id: str) -> Callable:
        """Wrap the agent callback so sandbox events include run_id."""
        cb = self._cb
        def wrapped(event_dict: dict) -> None:
            event_dict.setdefault("run_id", run_id)
            if cb:
                cb(event_dict)
        return wrapped

    def _emit(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        if self._cb:
            try:
                self._cb({
                    "run_id": run_id,
                    "node": self._node,
                    "agent": self._agent,
                    "event_type": event_type,
                    "payload": payload,
                })
            except Exception:
                pass
