"""
P2.6 — Architect ↔ Reviewer Loop (Feedback Loop FB2)
======================================================
Implements the FB2 loop from the IDEF0 model:

    Architect → Human Gate → [Developer → Tester] → Reviewer
    ↑                                                    |
    └──────── design flaws returned ────────────────────┘

Rules
-----
- Design flaws found by the Reviewer are sent back to the Architect.
- Implementation defects are passed to the FB1 loop (DeveloperTesterLoop).
- Maximum ``max_retries`` full cycles (default 3).
- On exhaustion → AGENT_ESCALATED + escalation report.
- Human gate is checked only on the FIRST design iteration (or after
  Architect revises due to design flaws); not re-checked on FB1 retries.

Events emitted
--------------
  RUN_STARTED / RUN_FINISHED / RUN_ESCALATED
  AGENT_RETRYING  (Architect re-design iteration)
  BUDGET_CHECKED
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.agents.architect import ArchitectAgent, DesignSpec
from ma_set.agents.developer import DeveloperAgent, DeveloperResult
from ma_set.agents.gate import GateDecision, GateMode, HumanGate
from ma_set.agents.loop import DeveloperTesterLoop
from ma_set.agents.reviewer import ReviewerAgent, ReviewVerdict
from ma_set.agents.tester import TesterAgent, TesterResult
from ma_set.config import Config
from ma_set.events.log import EventLog
from ma_set.events.schema import new_run_id
from ma_set.model.adapter import ModelAdapter
from ma_set.protection.path_filter import PathFilter
from ma_set.tools.code_index import CodeIndex


# ---------------------------------------------------------------------------
# Loop result
# ---------------------------------------------------------------------------

@dataclass
class Phase2Result:
    success: bool
    run_id: str
    design_iterations: int
    design_spec: Optional[DesignSpec]
    gate_decision: Optional[GateDecision]
    final_developer_result: Optional[DeveloperResult]
    final_tester_result: Optional[TesterResult]
    final_review_verdict: Optional[ReviewVerdict]
    escalation_report: str = ""


# ---------------------------------------------------------------------------
# FB2 Loop
# ---------------------------------------------------------------------------

class ArchitectReviewerLoop:
    """
    Full Phase 2 pipeline: Architect → Gate → Dev/Test → Reviewer → (retry).

    Parameters
    ----------
    adapter : ModelAdapter
    path_filter : PathFilter
    code_index : CodeIndex
    project_root : Path
    task_breakdown : str
        From the Planner (A1).
    gate_mode : GateMode
        AUTO_APPROVE in tests; INTERACTIVE for live demo.
    test_path : str
    src_path : str
    max_retries : int
    event_callback : callable, optional
    run_id : str, optional
    """

    def __init__(
        self,
        adapter: ModelAdapter,
        path_filter: PathFilter,
        code_index: CodeIndex,
        project_root: Path = Path("."),
        task_breakdown: str = "",
        gate_mode: GateMode = GateMode.AUTO_APPROVE,
        test_path: str = "demo_target/tests",
        src_path: str = "demo_target/app.py",
        max_retries: int = 3,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        run_id: Optional[str] = None,
    ):
        self._adapter = adapter
        self._pf = path_filter
        self._index = code_index
        self._root = project_root
        self._task_breakdown = task_breakdown
        self._gate_mode = gate_mode
        self._test_path = test_path
        self._src_path = src_path
        self._max_retries = max_retries
        self._cb = event_callback
        self._run_id = run_id or new_run_id()

        self._architect = ArchitectAgent(
            adapter=adapter,
            code_index=code_index,
            deny_list=Config.DENY_LIST,
            project_root=project_root,
            event_callback=event_callback,
            node="A2",
            agent="architect",
        )
        self._reviewer = ReviewerAgent(
            adapter=adapter,
            deny_list=Config.DENY_LIST,
            event_callback=event_callback,
            node="A4",
            agent="reviewer",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Phase2Result:
        run_id = self._run_id
        self._emit(run_id, "run_started", {
            "task_chars": len(self._task_breakdown),
            "max_retries": self._max_retries,
            "gate_mode": self._gate_mode,
        })

        design_feedback: List[str] = []
        gate_decision: Optional[GateDecision] = None
        design_spec: Optional[DesignSpec] = None
        dev_result: Optional[DeveloperResult] = None
        test_result: Optional[TesterResult] = None
        review_verdict: Optional[ReviewVerdict] = None

        for iteration in range(1, self._max_retries + 1):
            # ── Architect ──────────────────────────────────────────────
            if iteration > 1:
                self._emit(run_id, "agent_retrying", {
                    "iteration": iteration,
                    "design_feedback": design_feedback,
                })

            design_spec = self._architect.run(
                task_breakdown=self._task_breakdown,
                run_id=run_id,
                design_feedback=design_feedback if iteration > 1 else None,
                retry_number=iteration - 1,
            )

            # ── Human Gate (P2.4) ──────────────────────────────────────
            gate = HumanGate(
                mode=self._gate_mode,
                event_callback=self._cb,
                run_id=run_id,
                node="A2",
                agent="human_gate",
            )
            gate_decision = gate.check(design_spec.render(), run_id=run_id)

            if not gate_decision.approved:
                # Human rejected — treat as design flaw and retry if budget allows
                design_feedback = [f"Human rejected design: {gate_decision.comment}"]
                if iteration >= self._max_retries:
                    break
                continue

            # ── Developer + Tester (FB1) ───────────────────────────────
            fb1_loop = DeveloperTesterLoop(
                adapter=self._adapter,
                path_filter=self._pf,
                project_root=self._root,
                design_spec=design_spec.render(),
                test_path=self._test_path,
                src_path=self._src_path,
                max_retries=self._max_retries,
                event_callback=self._cb,
                run_id=run_id,
            )
            fb1_result = fb1_loop.run()
            dev_result = fb1_result.final_developer_result
            test_result = fb1_result.final_tester_result

            if not fb1_result.success:
                # FB1 exhausted — implementation too broken, escalate
                break

            # ── Reviewer (P2.5) ────────────────────────────────────────
            review_verdict = self._reviewer.run(
                design_spec=design_spec,
                developer_result=dev_result,
                tester_result=test_result,
                run_id=run_id,
            )

            # Budget check
            self._emit(run_id, "budget_checked", {
                "llm_calls": self._adapter.stats["call_count"],
                "iteration": iteration,
            })

            if review_verdict.approved:
                self._emit(run_id, "run_finished", {
                    "design_iterations": iteration,
                    "tests_passed": test_result.tests_passed,
                })
                return Phase2Result(
                    success=True,
                    run_id=run_id,
                    design_iterations=iteration,
                    design_spec=design_spec,
                    gate_decision=gate_decision,
                    final_developer_result=dev_result,
                    final_tester_result=test_result,
                    final_review_verdict=review_verdict,
                )

            # Reviewer rejected — split into design flaws (→ Architect)
            # and implementation defects (→ already handled by FB1)
            design_feedback = review_verdict.design_flaws or review_verdict.reasons

        # ── Escalation ────────────────────────────────────────────────
        report = self._build_escalation(
            run_id, design_feedback, design_spec,
            review_verdict, gate_decision,
        )
        self._emit(run_id, "run_escalated", {
            "report": report[:500],
            "design_iterations": self._max_retries,
        })
        return Phase2Result(
            success=False,
            run_id=run_id,
            design_iterations=self._max_retries,
            design_spec=design_spec,
            gate_decision=gate_decision,
            final_developer_result=dev_result,
            final_tester_result=test_result,
            final_review_verdict=review_verdict,
            escalation_report=report,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_escalation(
        run_id: str,
        design_feedback: List[str],
        spec: Optional[DesignSpec],
        verdict: Optional[ReviewVerdict],
        gate: Optional[GateDecision],
    ) -> str:
        lines = [
            "=== MA-SET PHASE 2 ESCALATION REPORT ===",
            f"Run ID : {run_id}",
            "Outcome: FAILED — all design iterations exhausted.",
            "",
        ]
        if gate and not gate.approved:
            lines += ["Human gate rejected:", f"  {gate.comment}", ""]
        if verdict and not verdict.approved:
            lines += ["Last review verdict: REJECTED"]
            for r in verdict.reasons:
                lines.append(f"  [FAIL] {r}")
            lines.append("")
        if design_feedback:
            lines += ["Last design feedback:"]
            for fb in design_feedback:
                lines.append(f"  • {fb}")
        lines += ["", "ACTION REQUIRED: Human review needed before proceeding."]
        return "\n".join(lines)

    def _emit(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        if self._cb:
            try:
                self._cb({
                    "run_id": run_id,
                    "node": "A6",
                    "agent": "loop_fb2",
                    "event_type": event_type,
                    "payload": payload,
                })
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def run_phase2(
    project_root: Path = Path("."),
    task_breakdown: str = "",
    gate_mode: GateMode = GateMode.AUTO_APPROVE,
    max_retries: int = 3,
    log_to_file: bool = True,
) -> Phase2Result:
    """One-shot entry point for Phase 2 (stub mode)."""
    run_id = new_run_id()
    log = EventLog(run_id=run_id) if log_to_file else None
    events: List[Dict] = []

    def callback(ev: dict) -> None:
        events.append(ev)
        if log:
            log.write_dict(ev)

    adapter = ModelAdapter(
        __import__("ma_set.model.adapter", fromlist=["ModelConfig"]).ModelConfig.from_env(),
        event_callback=callback,
    )
    pf = PathFilter(
        allow_list=Config.ALLOW_LIST,
        deny_list=Config.DENY_LIST,
        project_root=project_root,
        event_callback=callback,
        run_id=run_id,
        node="A3",
        agent="developer",
    )
    idx = CodeIndex(root=project_root)

    loop = ArchitectReviewerLoop(
        adapter=adapter,
        path_filter=pf,
        code_index=idx,
        project_root=project_root,
        task_breakdown=task_breakdown or "[stub] Fix signup validation",
        gate_mode=gate_mode,
        max_retries=max_retries,
        event_callback=callback,
        run_id=run_id,
    )
    result = loop.run()

    if log:
        print(f"\nAudit log -> {log.path}")
    print(f"Events : {len(events)}")
    print(f"Design iterations : {result.design_iterations}")
    print(f"Success : {result.success}")
    if not result.success:
        print(f"\n{result.escalation_report}")
    return result
