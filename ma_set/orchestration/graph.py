"""
P4.1, P4.2, P4.3, P4.4 — LangGraph Orchestration Graph
======================================================
Wires agents A1 to A5 into a unified LangGraph StateGraph, governed by Node A6.
Enforces:
  - Budget caps: max LLM calls per task.
  - Retry caps: max 3 retries for FB1 (Dev/Test) and FB2 (Arch/Review).
  - Audit trail persistence: all events saved to runs/{run_id}.jsonl.
  - Escalation handling: structured report when any cap is breached or gate fails.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from ma_set.agents.architect import ArchitectAgent, DesignSpec, ImpactReport
from ma_set.agents.developer import DeveloperAgent, DeveloperResult
from ma_set.agents.devops import DevOpsAgent, PullRequest, ReleaseNotes
from ma_set.agents.gate import GateDecision, GateMode, HumanGate
from ma_set.agents.planner import PlannerAgent, PlanResult
from ma_set.agents.reviewer import ReviewerAgent, ReviewVerdict
from ma_set.agents.tester import TesterAgent, TesterResult
from ma_set.config import Config
from ma_set.events.log import EventLog
from ma_set.events.schema import Event, EventType, new_run_id
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider
from ma_set.orchestration.state import EscalationReport, PipelineState
from ma_set.protection.path_filter import PathFilter
from ma_set.protection.regression_gate import RegressionGate, RegressionGateResult
from ma_set.tools.code_index import CodeIndex
from ma_set.tools.ticket_intake import Ticket, TicketIntake


@dataclass
class PipelineResult:
    """Consolidated outcome of an end-to-end pipeline run."""

    run_id: str
    ticket_id: str
    status: str  # "completed" | "escalated"
    success: bool
    plan: Optional[PlanResult] = None
    design_spec: Optional[DesignSpec] = None
    pr: Optional[PullRequest] = None
    release_notes: Optional[ReleaseNotes] = None
    escalation_report: Optional[EscalationReport] = None
    llm_calls_used: int = 0
    fb1_retries: int = 0
    fb2_retries: int = 0
    log_file: Optional[Path] = None


class PipelineOrchestrator:
    """
    Node A6: LangGraph-based central orchestrator.
    Manages state, enforces governance caps, persists audit trails, and runs tasks.
    """

    def __init__(
        self,
        project_root: Path = Config.PROJECT_ROOT,
        adapter: Optional[ModelAdapter] = None,
        max_llm_calls: int = Config.MAX_LLM_CALLS_PER_TASK,
        max_retries: int = Config.MAX_RETRIES_PER_LOOP,
        allow_list: Optional[List[str]] = None,
        deny_list: Optional[List[str]] = None,
        log_dir: Path = Config.RUNS_DIR,
        gate_mode: GateMode = GateMode.AUTO_APPROVE,
    ):
        self.project_root = Path(project_root).resolve()
        self.adapter = adapter or ModelAdapter(ModelConfig.from_env())
        self.max_llm_calls = max_llm_calls
        self.max_retries = max_retries
        self.allow_list = allow_list or Config.ALLOW_LIST
        self.deny_list = deny_list or Config.DENY_LIST
        self.log_dir = Path(log_dir)
        self.gate_mode = gate_mode
        self._event_sinks: Dict[str, Callable[[Dict[str, Any]], None]] = {}

        # Initialize shared components
        self.code_index = CodeIndex(project_root=self.project_root, deny_list=self.deny_list)
        self.app = self._build_graph()

    def _get_event_cb(self, run_id: str) -> Optional[Callable[[Dict[str, Any]], None]]:
        return self._event_sinks.get(run_id)

    # -----------------------------------------------------------------------
    # Graph Construction
    # -----------------------------------------------------------------------

    def _build_graph(self):
        builder = StateGraph(PipelineState)

        # Register nodes
        builder.add_node("planner", self._node_planner)
        builder.add_node("architect", self._node_architect)
        builder.add_node("human_gate", self._node_human_gate)
        builder.add_node("developer", self._node_developer)
        builder.add_node("tester", self._node_tester)
        builder.add_node("reviewer", self._node_reviewer)
        builder.add_node("regression_gate", self._node_regression_gate)
        builder.add_node("devops", self._node_devops)
        builder.add_node("escalate", self._node_escalate)

        # Edges
        builder.add_edge(START, "planner")

        builder.add_conditional_edges(
            "planner",
            self._route_after_planner,
            {"architect": "architect", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "architect",
            self._route_after_architect,
            {"human_gate": "human_gate", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "human_gate",
            self._route_after_gate,
            {"developer": "developer", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "developer",
            self._route_after_developer,
            {"tester": "tester", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "tester",
            self._route_after_tester,
            {"developer": "developer", "reviewer": "reviewer", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "reviewer",
            self._route_after_reviewer,
            {"architect": "architect", "regression_gate": "regression_gate", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "regression_gate",
            self._route_after_regression_gate,
            {"devops": "devops", "escalate": "escalate"},
        )
        builder.add_edge("devops", END)
        builder.add_edge("escalate", END)

        return builder.compile()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _check_budget(self, state: PipelineState, node_name: str) -> bool:
        """Enforces P4.2 budget cap: returns False if cap hit."""
        calls = self.adapter.call_count
        state["llm_calls_used"] = calls
        if calls > state["max_llm_calls"]:
            state["budget_exceeded"] = True
            state["failing_node"] = node_name
            state["escalation_reason"] = (
                f"Budget cap exceeded: {calls} LLM calls used (limit is {state['max_llm_calls']})"
            )
            return False
        return True

    # -----------------------------------------------------------------------
    # Node implementations
    # -----------------------------------------------------------------------

    def _node_planner(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        if not self._check_budget(state, "A1:planner"):
            return state

        ticket_data = state["ticket"]
        ticket = Ticket(**ticket_data)

        planner = PlannerAgent(
            adapter=self.adapter,
            event_callback=self._get_event_cb(run_id),
        )
        plan_res = planner.plan(ticket, run_id=run_id)

        return {
            "plan": {
                "ticket_id": plan_res.ticket_id,
                "title": plan_res.title,
                "summary": plan_res.summary,
                "user_stories": plan_res.user_stories,
                "tasks": plan_res.tasks,
                "acceptance_criteria": plan_res.acceptance_criteria,
                "formatted_breakdown": plan_res.formatted_breakdown,
                "was_refined": plan_res.was_refined,
            },
            "llm_calls_used": self.adapter.call_count,
        }

    def _node_architect(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        if not self._check_budget(state, "A2:architect"):
            return state

        plan_data = state["plan"] or {}
        task_breakdown = plan_data.get("formatted_breakdown", "")

        architect = ArchitectAgent(
            adapter=self.adapter,
            code_index=self.code_index,
            deny_list=self.deny_list,
            project_root=self.project_root,
            event_callback=self._get_event_cb(run_id),
        )

        feedback = state.get("reviewer_feedback")
        retry_num = state.get("fb2_retries", 0)

        spec = architect.run(
            task_breakdown=task_breakdown,
            run_id=run_id,
            design_feedback=feedback,
            retry_number=retry_num,
        )

        return {
            "design_spec": {
                "task_summary": spec.task_summary,
                "approach": spec.approach,
                "files_to_modify": spec.files_to_modify,
                "files_protected": spec.files_protected,
                "acceptance_criteria": spec.acceptance_criteria,
                "requires_signoff": spec.impact_report.requires_human_signoff,
                "rendered": spec.render(),
            },
            "llm_calls_used": self.adapter.call_count,
        }

    def _node_human_gate(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        spec_data = state["design_spec"] or {}
        spec_rendered = spec_data.get("rendered", "")

        gate = HumanGate(
            mode=self.gate_mode,
            event_callback=self._get_event_cb(run_id),
        )

        decision: GateDecision = gate.check(spec_rendered, run_id=run_id)

        if not decision.approved:
            return {
                "gate_approved": False,
                "gate_feedback": decision.comment,
                "failing_node": "A2:human_gate",
                "escalation_reason": f"Human design sign-off rejected: {decision.comment}",
            }

        return {
            "gate_approved": True,
            "gate_feedback": decision.comment,
        }

    def _node_developer(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        if not self._check_budget(state, "A3:developer"):
            return state

        pf = PathFilter(
            allow_list=self.allow_list,
            deny_list=self.deny_list,
            project_root=self.project_root,
            event_callback=self._get_event_cb(run_id),
            run_id=run_id,
        )

        dev = DeveloperAgent(
            adapter=self.adapter,
            path_filter=pf,
            project_root=self.project_root,
            event_callback=self._get_event_cb(run_id),
        )

        spec_data = state["design_spec"] or {}
        spec_text = spec_data.get("rendered", "")
        defects = state.get("tester_defect_list")
        retry_num = state.get("fb1_retries", 0)

        # Snapshot workspace files to ensure read-only main branch invariant
        pre_run_snapshot: Dict[str, str] = {}
        for allowed in self.allow_list:
            fpath = self.project_root / allowed
            if fpath.is_file():
                try:
                    pre_run_snapshot[allowed] = fpath.read_text(encoding="utf-8")
                except Exception:
                    pass

        try:
            dev_res: DeveloperResult = dev.run(
                design_spec=spec_text,
                run_id=run_id,
                defect_list=defects,
                retry_number=retry_num,
            )
        finally:
            # Restore main workspace so main branch remains pristine
            for rel_path, content in pre_run_snapshot.items():
                try:
                    (self.project_root / rel_path).write_text(content, encoding="utf-8")
                except Exception:
                    pass

        if not dev_res.success:
            return {
                "developer_patched": False,
                "developer_diff": "",
                "failing_node": "A3:developer",
                "escalation_reason": f"Developer implementation failed: {dev_res.error}",
            }

        return {
            "developer_patched": True,
            "developer_diff": dev_res.diff,
            "developer_patched_contents": dev_res.patched_contents,
            "llm_calls_used": self.adapter.call_count,
        }

    def _node_tester(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        tester = TesterAgent(
            project_root=self.project_root,
            test_path="demo_target/tests",
            run_lint=False,
            event_callback=self._get_event_cb(run_id),
        )

        # Pass developer's patch into disposable sandbox
        patched_contents = dict(state.get("developer_patched_contents") or {})
        if not patched_contents and state.get("developer_patched"):
            app_path = self.project_root / "demo_target" / "app.py"
            if app_path.exists():
                patched_contents["demo_target/app.py"] = app_path.read_text(encoding="utf-8")

        test_res: TesterResult = tester.run(
            run_id=run_id,
            patched_files=patched_contents,
        )

        retries = state.get("fb1_retries", 0)
        new_retries = retries if test_res.success else retries + 1

        return {
            "tester_success": test_res.success,
            "tester_defect_list": test_res.defect_list,
            "tests_passed": test_res.tests_passed,
            "tests_failed": test_res.tests_failed,
            "fb1_retries": new_retries,
        }

    def _node_reviewer(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        if not self._check_budget(state, "A4:reviewer"):
            return state

        reviewer = ReviewerAgent(
            adapter=self.adapter,
            deny_list=self.deny_list,
            event_callback=self._get_event_cb(run_id),
        )

        spec_data = state["design_spec"] or {}
        dummy_ir = ImpactReport(
            files_to_modify=spec_data.get("files_to_modify", []),
            files_to_read=[],
            protected_files_touched=[],
            symbols_changed=[],
            summary="",
        )
        spec = DesignSpec(
            task_summary=spec_data.get("task_summary", ""),
            approach=spec_data.get("approach", ""),
            files_to_modify=spec_data.get("files_to_modify", []),
            files_protected=spec_data.get("files_protected", []),
            acceptance_criteria=spec_data.get("acceptance_criteria", []),
            impact_report=dummy_ir,
        )

        diff = state.get("developer_diff", "")
        tests_passed = state.get("tester_success", False)

        dev_res = DeveloperResult(
            success=state.get("developer_patched", False),
            diff=diff,
            files_changed=spec.files_to_modify,
            patched_contents={},
        )
        tester_res = TesterResult(
            tests_total=state.get("tests_passed", 0) + state.get("tests_failed", 0),
            tests_passed=state.get("tests_passed", 0),
            tests_failed=state.get("tests_failed", 0),
            tests_xfailed=0,
            defect_list=state.get("tester_defect_list", []),
            lint_errors=[],
            raw_pytest_output="",
            raw_lint_output="",
            success=tests_passed,
        )

        verdict: ReviewVerdict = reviewer.run(
            design_spec=spec,
            developer_result=dev_res,
            tester_result=tester_res,
            run_id=run_id,
        )

        retries = state.get("fb2_retries", 0)
        new_retries = retries if verdict.approved else retries + 1

        return {
            "reviewer_approved": verdict.approved,
            "reviewer_feedback": verdict.feedback_for_architect,
            "fb2_retries": new_retries,
            "llm_calls_used": self.adapter.call_count,
        }

    def _node_regression_gate(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        reg_gate = RegressionGate(
            baseline_passed_count=3,
            event_callback=self._get_event_cb(run_id),
        )

        mock_tr = TesterResult(
            tests_total=state.get("tests_passed", 0) + state.get("tests_failed", 0),
            tests_passed=state.get("tests_passed", 0),
            tests_failed=state.get("tests_failed", 0),
            tests_xfailed=0,
            defect_list=state.get("tester_defect_list", []),
            lint_errors=[],
            raw_pytest_output="",
            raw_lint_output="",
            success=state.get("tester_success", False),
        )

        res: RegressionGateResult = reg_gate.check(mock_tr, run_id=run_id)

        if not res.passed:
            return {
                "regression_passed": False,
                "failing_node": "A5:regression_gate",
                "escalation_reason": f"Regression detected: {res.summary}",
            }

        return {"regression_passed": True}

    def _node_devops(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        devops = DevOpsAgent(
            project_root=self.project_root,
            event_callback=self._get_event_cb(run_id),
        )

        ticket = Ticket(**state["ticket"])
        spec_data = state["design_spec"] or {}
        dummy_ir = ImpactReport(
            files_to_modify=spec_data.get("files_to_modify", []),
            files_to_read=[],
            protected_files_touched=[],
            symbols_changed=[],
            summary="",
        )
        spec = DesignSpec(
            task_summary=spec_data.get("task_summary", ""),
            approach=spec_data.get("approach", ""),
            files_to_modify=spec_data.get("files_to_modify", []),
            files_protected=spec_data.get("files_protected", []),
            acceptance_criteria=spec_data.get("acceptance_criteria", []),
            impact_report=dummy_ir,
        )

        diff = state.get("developer_diff", "")

        pr = devops.open_pull_request(
            ticket=ticket,
            design_spec=spec,
            diff=diff,
            run_id=run_id,
        )

        rn = devops.generate_release_notes(
            ticket=ticket,
            design_spec=spec,
            diff=diff,
            run_id=run_id,
        )

        return {
            "status": "completed",
            "pr": pr.__dict__,
            "release_notes": rn.__dict__,
            "end_time": datetime.now(timezone.utc).isoformat(),
        }

    def _node_escalate(self, state: PipelineState) -> Dict[str, Any]:
        run_id = state["run_id"]
        ticket_id = state["ticket"].get("id", "UNKNOWN")
        failing_node = state.get("failing_node", "A6:orchestrator")
        reason = state.get("escalation_reason", "Unspecified failure")

        report = EscalationReport(
            run_id=run_id,
            ticket_id=ticket_id,
            failing_node=failing_node,
            reason=reason,
            fb1_retries=state.get("fb1_retries", 0),
            fb2_retries=state.get("fb2_retries", 0),
            llm_calls_used=state.get("llm_calls_used", 0),
            max_llm_calls=state.get("max_llm_calls", 20),
            defects=state.get("tester_defect_list", []),
            review_feedback=state.get("reviewer_feedback", []),
        )

        # Emit escalation event
        event_cb = self._get_event_cb(run_id)
        if event_cb:
            ev = Event.make(
                run_id=run_id,
                node="A6",
                agent="orchestrator",
                event_type=EventType.RUN_ESCALATED,
                payload={
                    "ticket_id": ticket_id,
                    "failing_node": failing_node,
                    "reason": reason,
                    "report": report.render(),
                },
            )
            event_cb(ev.model_dump())

        return {
            "status": "escalated",
            "escalation_report": report.render(),
            "end_time": datetime.now(timezone.utc).isoformat(),
        }

    # -----------------------------------------------------------------------
    # Conditional edge routers
    # -----------------------------------------------------------------------

    def _route_after_planner(self, state: PipelineState) -> str:
        if state.get("budget_exceeded") or not state.get("plan"):
            return "escalate"
        return "architect"

    def _route_after_architect(self, state: PipelineState) -> str:
        if state.get("budget_exceeded") or not state.get("design_spec"):
            return "escalate"
        return "human_gate"

    def _route_after_gate(self, state: PipelineState) -> str:
        if not state.get("gate_approved"):
            return "escalate"
        return "developer"

    def _route_after_developer(self, state: PipelineState) -> str:
        if state.get("budget_exceeded") or not state.get("developer_patched"):
            return "escalate"
        return "tester"

    def _route_after_tester(self, state: PipelineState) -> str:
        if state.get("tester_success"):
            return "reviewer"

        retries = state.get("fb1_retries", 0)
        max_r = state.get("max_retries", 3)
        if retries <= max_r:
            return "developer"  # FB1 retry loop

        state["failing_node"] = "A4:tester"
        state["escalation_reason"] = (
            f"FB1 retry cap reached ({max_r} attempts): defects unresolved"
        )
        return "escalate"

    def _route_after_reviewer(self, state: PipelineState) -> str:
        if state.get("budget_exceeded"):
            return "escalate"

        if state.get("reviewer_approved"):
            return "regression_gate"

        retries = state.get("fb2_retries", 0)
        max_r = state.get("max_retries", 3)
        if retries <= max_r:
            return "architect"  # FB2 retry loop

        state["failing_node"] = "A4:reviewer"
        state["escalation_reason"] = (
            f"FB2 review rejection cap reached ({max_r} attempts)"
        )
        return "escalate"

    def _route_after_regression_gate(self, state: PipelineState) -> str:
        if not state.get("regression_passed"):
            return "escalate"
        return "devops"

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(
        self,
        ticket: Ticket,
        run_id: Optional[str] = None,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> PipelineResult:
        """
        Execute an end-to-end task run through the LangGraph pipeline.
        Logs all events to runs/{run_id}.jsonl.
        """
        rid = run_id or new_run_id()
        event_log = EventLog(run_id=rid, log_dir=self.log_dir)

        # Event emission callback
        events_captured: List[Dict[str, Any]] = []

        def _sink(event_dict: Dict[str, Any]) -> None:
            events_captured.append(event_dict)
            event_log.write_dict(event_dict)
            if event_sink:
                try:
                    event_sink(event_dict)
                except Exception:
                    pass

        # Emit RUN_STARTED
        start_ev = Event.make(
            run_id=rid,
            node="A6",
            agent="orchestrator",
            event_type=EventType.RUN_STARTED,
            payload={"ticket_id": ticket.id, "title": ticket.title},
        )
        _sink(start_ev.model_dump())

        # Initial state
        initial_state: PipelineState = {
            "run_id": rid,
            "status": "running",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "ticket": ticket.model_dump(),
            "plan": None,
            "design_spec": None,
            "gate_approved": False,
            "gate_feedback": "",
            "developer_diff": "",
            "developer_patched": False,
            "developer_patched_contents": {},
            "tester_success": False,
            "tester_defect_list": [],
            "tests_passed": 0,
            "tests_failed": 0,
            "fb1_retries": 0,
            "reviewer_approved": False,
            "reviewer_feedback": [],
            "fb2_retries": 0,
            "regression_passed": False,
            "pr": None,
            "release_notes": None,
            "llm_calls_used": self.adapter.call_count,
            "max_llm_calls": self.max_llm_calls,
            "max_retries": self.max_retries,
            "budget_exceeded": False,
            "escalation_reason": None,
            "escalation_report": None,
            "failing_node": None,
        }

        # Register sink for node access
        self._event_sinks[rid] = _sink

        # Run the graph
        try:
            final_state = self.app.invoke(initial_state)
        finally:
            self._event_sinks.pop(rid, None)

        success = final_state.get("status") == "completed"

        # Emit RUN_FINISHED if completed
        if success:
            finish_ev = Event.make(
                run_id=rid,
                node="A6",
                agent="orchestrator",
                event_type=EventType.RUN_FINISHED,
                payload={
                    "ticket_id": ticket.id,
                    "status": "completed",
                    "pr_number": final_state.get("pr", {}).get("number"),
                    "llm_calls_used": self.adapter.call_count,
                    "max_llm_calls": final_state.get("max_llm_calls", 20),
                },
            )
            _sink(finish_ev.model_dump())

        # Construct PipelineResult
        plan_obj = None
        if final_state.get("plan"):
            p_dict = final_state["plan"]
            plan_obj = PlanResult(
                ticket_id=p_dict["ticket_id"],
                title=p_dict["title"],
                summary=p_dict["summary"],
                user_stories=p_dict["user_stories"],
                tasks=p_dict["tasks"],
                acceptance_criteria=p_dict["acceptance_criteria"],
                was_refined=p_dict.get("was_refined", False),
            )

        spec_obj = None
        if final_state.get("design_spec"):
            s_dict = final_state["design_spec"]
            ir = ImpactReport(
                files_to_modify=s_dict.get("files_to_modify", []),
                files_to_read=[],
                protected_files_touched=[],
                symbols_changed=[],
                summary="",
            )
            spec_obj = DesignSpec(
                task_summary=s_dict.get("task_summary", ""),
                approach=s_dict.get("approach", ""),
                files_to_modify=s_dict.get("files_to_modify", []),
                files_protected=s_dict.get("files_protected", []),
                acceptance_criteria=s_dict.get("acceptance_criteria", []),
                impact_report=ir,
            )

        pr_obj = PullRequest(**final_state["pr"]) if final_state.get("pr") else None
        rn_obj = ReleaseNotes(**final_state["release_notes"]) if final_state.get("release_notes") else None

        esc_report = None
        if final_state.get("escalation_report"):
            esc_report = EscalationReport(
                run_id=rid,
                ticket_id=ticket.id,
                failing_node=final_state.get("failing_node", "A6"),
                reason=final_state.get("escalation_reason", "Failure"),
                fb1_retries=final_state.get("fb1_retries", 0),
                fb2_retries=final_state.get("fb2_retries", 0),
                llm_calls_used=final_state.get("llm_calls_used", 0),
                max_llm_calls=self.max_llm_calls,
                defects=final_state.get("tester_defect_list", []),
                review_feedback=final_state.get("reviewer_feedback", []),
            )

        return PipelineResult(
            run_id=rid,
            ticket_id=ticket.id,
            status=final_state.get("status", "escalated"),
            success=success,
            plan=plan_obj,
            design_spec=spec_obj,
            pr=pr_obj,
            release_notes=rn_obj,
            escalation_report=esc_report,
            llm_calls_used=self.adapter.call_count,
            fb1_retries=final_state.get("fb1_retries", 0),
            fb2_retries=final_state.get("fb2_retries", 0),
            log_file=event_log.path,
        )
