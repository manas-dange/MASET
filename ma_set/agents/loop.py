"""
P1.5 — Developer ↔ Tester Retry Loop (Feedback Loop FB1)
===========================================================
Implements the FB1 loop from the IDEF0 model:

    Developer → Tester → [defects?] → Developer (retry) → …

Rules
-----
- Maximum ``max_retries`` attempts (default 3, per the spec).
- On each retry the defect list from the previous Tester run is injected
  into the Developer prompt so the LLM can address specific failures.
- If all retries are exhausted without passing tests, the loop emits
  AGENT_ESCALATED and returns a structured escalation report.
- If tests pass, the loop emits RUN_FINISHED and returns the result.

Events emitted (P1.6)
---------------------
  RUN_STARTED
  AGENT_RETRYING  (on each retry with defects)
  BUDGET_CHECKED  (after each LLM call via the adapter)
  AGENT_ESCALATED (on loop exhaustion)
  RUN_FINISHED    (on success)
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.agents.developer import DeveloperAgent, DeveloperResult
from ma_set.agents.tester import TesterAgent, TesterResult
from ma_set.events.log import EventLog
from ma_set.events.schema import new_run_id
from ma_set.model.adapter import ModelAdapter
from ma_set.protection.path_filter import PathFilter


# ---------------------------------------------------------------------------
# Loop result
# ---------------------------------------------------------------------------

@dataclass
class LoopResult:
    success: bool
    run_id: str
    attempts: int
    final_developer_result: Optional[DeveloperResult]
    final_tester_result: Optional[TesterResult]
    escalation_report: str = ""     # non-empty on failure


# ---------------------------------------------------------------------------
# FB1 loop
# ---------------------------------------------------------------------------

class DeveloperTesterLoop:
    """
    Orchestrates the Developer → Tester → (retry) loop.

    Parameters
    ----------
    adapter : ModelAdapter
    path_filter : PathFilter
    project_root : Path
    design_spec : str
        The spec passed to the Developer for its first attempt.
    test_path : str
        Passed to TesterAgent.
    src_path : str
        Source file for linting.
    max_retries : int
        Maximum number of Developer→Tester cycles (spec says 3).
    event_callback : callable, optional
        Receives all events from both agents and the loop itself.
    run_id : str, optional
        Provide an existing run ID or let the loop generate a new one.
    """

    def __init__(
        self,
        adapter: ModelAdapter,
        path_filter: PathFilter,
        project_root: Path = Path("."),
        design_spec: str = "",
        test_path: str = "demo_target/tests",
        src_path: str = "demo_target/app.py",
        max_retries: int = 3,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        run_id: Optional[str] = None,
    ):
        self._adapter = adapter
        self._pf = path_filter
        self._root = project_root
        self._design_spec = design_spec
        self._test_path = test_path
        self._src_path = src_path
        self._max_retries = max_retries
        self._cb = event_callback
        self._run_id = run_id or new_run_id()

        # Build child agents (they share the same callback so all events
        # funnel through the same log)
        self._developer = DeveloperAgent(
            adapter=adapter,
            path_filter=path_filter,
            project_root=project_root,
            event_callback=event_callback,
            node="A3",
            agent="developer",
        )
        self._tester = TesterAgent(
            project_root=project_root,
            test_path=test_path,
            src_path=src_path,
            run_lint=True,
            event_callback=event_callback,
            node="A4",
            agent="tester",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> LoopResult:
        """Execute the FB1 loop and return a LoopResult."""
        run_id = self._run_id
        self._emit(run_id, "run_started", {
            "design_spec_chars": len(self._design_spec),
            "max_retries": self._max_retries,
        })

        defect_list: List[str] = []
        dev_result: Optional[DeveloperResult] = None
        test_result: Optional[TesterResult] = None

        for attempt in range(1, self._max_retries + 1):
            # ---- Developer ----
            if attempt > 1:
                self._emit(run_id, "agent_retrying", {
                    "attempt": attempt,
                    "defects": defect_list,
                })

            dev_result = self._developer.run(
                design_spec=self._design_spec,
                run_id=run_id,
                defect_list=defect_list if attempt > 1 else None,
                retry_number=attempt - 1,
            )

            if not dev_result.success:
                # Developer itself failed — escalate immediately
                break

            # ---- Tester ----
            test_result = self._tester.run(
                run_id=run_id,
                patched_files=dev_result.patched_contents,
            )

            # Budget check
            self._emit(run_id, "budget_checked", {
                "llm_calls": self._adapter.stats["call_count"],
                "attempt": attempt,
            })

            if test_result.success:
                self._emit(run_id, "run_finished", {
                    "attempts": attempt,
                    "tests_passed": test_result.tests_passed,
                    "tests_total": test_result.tests_total,
                })
                return LoopResult(
                    success=True,
                    run_id=run_id,
                    attempts=attempt,
                    final_developer_result=dev_result,
                    final_tester_result=test_result,
                )

            defect_list = test_result.defect_list

        # ---- Escalation ----
        report = self._build_escalation_report(
            run_id, defect_list, dev_result, test_result
        )
        self._emit(run_id, "run_escalated", {
            "report": report[:500],
            "attempts": self._max_retries,
        })
        return LoopResult(
            success=False,
            run_id=run_id,
            attempts=self._max_retries,
            final_developer_result=dev_result,
            final_tester_result=test_result,
            escalation_report=report,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_escalation_report(
        run_id: str,
        defects: List[str],
        dev: Optional[DeveloperResult],
        test: Optional[TesterResult],
    ) -> str:
        lines = [
            "=== MA-SET ESCALATION REPORT ===",
            f"Run ID  : {run_id}",
            f"Outcome : FAILED — all retries exhausted",
            "",
            "Last defects:",
        ]
        for d in defects:
            lines.append(f"  • {d}")
        if test:
            lines.append("")
            lines.append(
                f"Test summary: {test.tests_passed} passed / "
                f"{test.tests_failed} failed / {test.tests_xfailed} xfailed"
            )
        if dev and dev.diff:
            lines.append("")
            lines.append("Last diff snippet:")
            lines.append(textwrap.indent(dev.diff[:400], "  "))
        lines.append("")
        lines.append("ACTION REQUIRED: Human review needed before proceeding.")
        return "\n".join(lines)

    def _emit(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        if self._cb:
            try:
                self._cb({
                    "run_id": run_id,
                    "node": "A6",
                    "agent": "loop_fb1",
                    "event_type": event_type,
                    "payload": payload,
                })
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def run_phase1(
    project_root: Path = Path("."),
    design_spec: str = "",
    max_retries: int = 3,
    log_to_file: bool = True,
) -> LoopResult:
    """
    One-shot entry point for Phase 1 (stub mode).

    Sets up the adapter, path filter, event log, and loop — then runs.
    """
    from ma_set.config import Config
    from ma_set.model.adapter import ModelAdapter, ModelConfig

    run_id = new_run_id()
    log = EventLog(run_id=run_id) if log_to_file else None

    events_seen: List[Dict] = []

    def callback(ev: dict) -> None:
        events_seen.append(ev)
        if log:
            log.write_dict(ev)

    adapter = ModelAdapter(ModelConfig.from_env(), event_callback=callback)
    pf = PathFilter(
        allow_list=Config.ALLOW_LIST,
        deny_list=Config.DENY_LIST,
        project_root=project_root,
        event_callback=callback,
        run_id=run_id,
        node="A3",
        agent="developer",
    )

    loop = DeveloperTesterLoop(
        adapter=adapter,
        path_filter=pf,
        project_root=project_root,
        design_spec=design_spec or "[stub] Fix signup validation",
        max_retries=max_retries,
        event_callback=callback,
        run_id=run_id,
    )

    result = loop.run()

    if log:
        print(f"\nAudit log saved -> {log.path}")
    print(f"Events captured  : {len(events_seen)}")
    print(f"Attempts         : {result.attempts}")
    print(f"Success          : {result.success}")
    if not result.success:
        print(f"\n{result.escalation_report}")

    return result
