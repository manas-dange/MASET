"""
P3.3 — Regression Gate
=======================
Node A5: Enforces that existing passing tests continue to pass before any PR is opened.
Prevents unintended regressions introduced by agent patches.

Safety check:
  - Compares test outcomes against baseline (or verifies 0 test failures / 0 collection errors).
  - Emits REGRESSION_GATE_PASSED or REGRESSION_GATE_FAILED events into the audit trail.
  - Blocks downstream PR creation if regressions are detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from ma_set.agents.tester import TesterResult

from ma_set.events.schema import Event, EventType


class RegressionError(RuntimeError):
    """Raised when the regression gate detects broken tests."""


@dataclass
class RegressionGateResult:
    """Outcome of regression gate evaluation."""

    passed: bool
    baseline_passed: int
    current_passed: int
    current_failed: int
    regressions: List[str] = field(default_factory=list)
    summary: str = ""

    def render(self) -> str:
        status_symbol = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== REGRESSION GATE: {status_symbol} ===",
            f"Baseline passed: {self.baseline_passed}",
            f"Current passed:  {self.current_passed}",
            f"Current failed:  {self.current_failed}",
            f"Summary:         {self.summary}",
        ]
        if self.regressions:
            lines.append("Detected Regressions:")
            for r in self.regressions:
                lines.append(f"  * {r}")
        return "\n".join(lines)


class RegressionGate:
    """
    Validates that changes do not introduce regressions into the test suite.
    """

    def __init__(
        self,
        baseline_passed_count: int = 0,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A5",
        agent: str = "regression_gate",
    ):
        self._baseline_passed = baseline_passed_count
        self._callback = event_callback
        self._node = node
        self._agent = agent

    def _emit(self, event_type: EventType, run_id: str, payload: Dict[str, Any]) -> None:
        if self._callback:
            ev = Event.make(
                run_id=run_id,
                node=self._node,
                agent=self._agent,
                event_type=event_type,
                payload=payload,
            )
            self._callback(ev.model_dump())

    def check(
        self,
        tester_result: TesterResult,
        run_id: str,
        baseline_passed: Optional[int] = None,
    ) -> RegressionGateResult:
        """
        Evaluate a TesterResult against regression criteria.
        """
        base_passed = baseline_passed if baseline_passed is not None else self._baseline_passed

        # Check conditions
        regressions: List[str] = []
        if tester_result.tests_failed > 0:
            regressions.extend(tester_result.defect_list)

        if not tester_result.success and not regressions:
            regressions.append(f"Test run failed with exit code {tester_result.exit_code}")

        # Check for passing test count drop (if baseline specified > 0)
        if base_passed > 0 and tester_result.tests_passed < base_passed:
            regressions.append(
                f"Passing test count dropped from {base_passed} to {tester_result.tests_passed}"
            )

        passed = len(regressions) == 0 and (tester_result.success or tester_result.exit_code == 0)

        summary = (
            f"All {tester_result.tests_passed} tests passed with 0 regressions."
            if passed
            else f"Regression detected: {len(regressions)} defect(s) / failure(s) found."
        )

        result = RegressionGateResult(
            passed=passed,
            baseline_passed=base_passed,
            current_passed=tester_result.tests_passed,
            current_failed=tester_result.tests_failed,
            regressions=regressions,
            summary=summary,
        )

        event_type = EventType.REGRESSION_GATE_PASSED if passed else EventType.REGRESSION_GATE_FAILED
        self._emit(
            event_type,
            run_id=run_id,
            payload={
                "passed": passed,
                "baseline_passed": base_passed,
                "current_passed": tester_result.tests_passed,
                "current_failed": tester_result.tests_failed,
                "regressions": regressions,
                "summary": summary,
            },
        )

        return result
