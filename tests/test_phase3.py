"""
Phase 3 Tests — Intake & Delivery (P3.1–P3.7)
=============================================
Covers:
  - P3.1: Ticket Intake (YAML parsing, validation, directory sorting, saving)
  - P3.2: Planner Agent with Ticket Refinement (user stories, tasks, criteria)
  - P3.3: Regression Gate (baseline comparison, failure blocking)
  - P3.4: DevOps Agent (branching, PR opening, audit metadata)
  - P3.5: Human-Only Merge Enforcement (permission block, event emission)
  - P3.6: Release Notes Generation (markdown formatting, traceability)
  - P3.7: Feedback Loop FB3 (converting post-release feedback into intake tickets)
  - End-to-End intake to PR flow
"""

from __future__ import annotations

from pathlib import Path
import pytest

from ma_set.agents.architect import DesignSpec, ImpactReport
from ma_set.agents.devops import DevOpsAgent, PullRequest, ReleaseNotes
from ma_set.agents.fb3_loop import FeedbackConverter, FeedbackItem
from ma_set.agents.planner import PlannerAgent, PlanResult
from ma_set.agents.tester import TesterResult
from ma_set.events.schema import EventType
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider
from ma_set.protection.regression_gate import RegressionError, RegressionGate, RegressionGateResult
from ma_set.tools.ticket_intake import Ticket, TicketIntake, TicketPriority, TicketType


# ===========================================================================
# Fixtures & Helpers
# ===========================================================================

@pytest.fixture
def sample_ticket() -> Ticket:
    return Ticket(
        id="DEMO-001",
        title="Add input validation to /signup endpoint",
        description="Ensure email and password fields are present and return 400 on error.",
        type=TicketType.BUG,
        priority=TicketPriority.HIGH,
        acceptance_criteria=[
            "POST /signup with missing email returns 400",
            "POST /signup with missing password returns 400",
            "POST /signup with valid payload returns 201",
        ],
        labels=["validation", "auth"],
    )


@pytest.fixture
def vague_ticket() -> Ticket:
    return Ticket(
        id="TICK-099",
        title="Fix login bug",
        description="Login is broken",  # short description, no acceptance criteria
        type=TicketType.BUG,
        priority=TicketPriority.MEDIUM,
    )


@pytest.fixture
def stub_adapter() -> ModelAdapter:
    return ModelAdapter(ModelConfig(provider=Provider.STUB))


@pytest.fixture
def dummy_design_spec() -> DesignSpec:
    return DesignSpec(
        task_summary="Add input validation to /signup endpoint",
        approach="Add validation helper in app.py",
        files_to_modify=["demo_target/app.py"],
        files_protected=["demo_target/legacy_billing.py"],
        acceptance_criteria=[
            "POST /signup with missing email returns 400",
            "POST /signup with valid payload returns 201",
        ],
        impact_report=ImpactReport(
            files_to_modify=["demo_target/app.py"],
            files_to_read=["demo_target/legacy_billing.py"],
            protected_files_touched=[],
            symbols_changed=["signup"],
            summary="1 file modified",
        ),
    )


# ===========================================================================
# P3.1: Ticket Intake Tests
# ===========================================================================

class TestTicketIntake:
    def test_load_ticket_from_yaml_file(self, tmp_path: Path):
        events = []
        intake = TicketIntake(event_callback=events.append)

        ticket_file = tmp_path / "test_ticket.yaml"
        ticket_file.write_text("""
id: DEMO-001
title: Add input validation
description: Detailed problem statement describing signup endpoint validation.
type: bug
priority: high
acceptance_criteria:
  - Criterion 1
  - Criterion 2
labels:
  - auth
""")

        ticket = intake.load_ticket(ticket_file, run_id="run-intake-1")
        assert ticket.id == "DEMO-001"
        assert ticket.title == "Add input validation"
        assert ticket.type == TicketType.BUG
        assert ticket.priority == TicketPriority.HIGH
        assert len(ticket.acceptance_criteria) == 2
        assert not ticket.is_vague()

        # Audit event
        ingested_events = [e for e in events if e["event_type"] == EventType.TICKET_INGESTED.value]
        assert len(ingested_events) == 1
        assert ingested_events[0]["payload"]["ticket_id"] == "DEMO-001"

    def test_vague_ticket_detection(self, vague_ticket: Ticket):
        assert vague_ticket.is_vague() is True

    def test_load_multiple_tickets_sorted_by_priority(self, tmp_path: Path):
        intake = TicketIntake()

        t_low = tmp_path / "low.yaml"
        t_low.write_text("id: T-LOW\ntitle: Low priority task\npriority: low\n")

        t_crit = tmp_path / "crit.yaml"
        t_crit.write_text("id: T-CRIT\ntitle: Critical bug\npriority: critical\n")

        t_high = tmp_path / "high.yaml"
        t_high.write_text("id: T-HIGH\ntitle: High bug\npriority: high\n")

        tickets = intake.load_tickets_from_dir(tmp_path)
        assert len(tickets) == 3
        assert tickets[0].id == "T-CRIT"
        assert tickets[1].id == "T-HIGH"
        assert tickets[2].id == "T-LOW"

    def test_save_and_reload_ticket(self, tmp_path: Path, sample_ticket: Ticket):
        intake = TicketIntake()
        saved_path = intake.save_ticket(sample_ticket, tmp_path)
        assert saved_path.exists()

        reloaded = intake.load_ticket(saved_path)
        assert reloaded.id == sample_ticket.id
        assert reloaded.title == sample_ticket.title
        assert reloaded.acceptance_criteria == sample_ticket.acceptance_criteria


# ===========================================================================
# P3.2: Planner Agent & Ticket Refinement Tests
# ===========================================================================

class TestPlannerAgent:
    def test_planner_produces_structured_plan_in_stub_mode(
        self, stub_adapter: ModelAdapter, sample_ticket: Ticket
    ):
        events = []
        planner = PlannerAgent(adapter=stub_adapter, event_callback=events.append)

        plan = planner.plan(sample_ticket, run_id="run-plan-1")
        assert isinstance(plan, PlanResult)
        assert plan.ticket_id == sample_ticket.id
        assert len(plan.user_stories) > 0
        assert len(plan.tasks) > 0
        assert len(plan.acceptance_criteria) > 0
        assert "TICKET:" in plan.formatted_breakdown
        assert "USER STORIES:" in plan.formatted_breakdown

        # Event audit verification
        event_types = [e["event_type"] for e in events]
        assert EventType.AGENT_STARTED.value in event_types
        assert EventType.PLAN_PRODUCED.value in event_types
        assert EventType.AGENT_FINISHED.value in event_types

    def test_planner_refines_vague_ticket(
        self, stub_adapter: ModelAdapter, vague_ticket: Ticket
    ):
        events = []
        planner = PlannerAgent(adapter=stub_adapter, event_callback=events.append)

        plan = planner.plan(vague_ticket, run_id="run-plan-2")
        assert plan.was_refined is True
        assert len(plan.acceptance_criteria) > 0

        refined_events = [e for e in events if e["event_type"] == EventType.TICKET_REFINED.value]
        assert len(refined_events) == 1
        assert refined_events[0]["payload"]["ticket_id"] == vague_ticket.id


# ===========================================================================
# P3.3: Regression Gate Tests
# ===========================================================================

class TestRegressionGate:
    def test_regression_gate_passes_when_all_tests_succeed(self):
        events = []
        gate = RegressionGate(baseline_passed_count=5, event_callback=events.append)

        mock_tester_result = TesterResult(
            tests_total=8,
            tests_passed=6,
            tests_failed=0,
            tests_xfailed=2,
            defect_list=[],
            lint_errors=[],
            raw_pytest_output="6 passed, 2 xfailed",
            raw_lint_output="",
            success=True,
        )

        res = gate.check(mock_tester_result, run_id="run-reg-1")
        assert res.passed is True
        assert res.current_passed == 6
        assert len(res.regressions) == 0
        assert "PASSED" in res.render()

        event_types = [e["event_type"] for e in events]
        assert EventType.REGRESSION_GATE_PASSED.value in event_types

    def test_regression_gate_fails_when_defects_exist(self):
        events = []
        gate = RegressionGate(baseline_passed_count=5, event_callback=events.append)

        mock_failing_result = TesterResult(
            tests_total=7,
            tests_passed=4,
            tests_failed=1,
            tests_xfailed=2,
            defect_list=["FAILED test_app.py::test_signup - AssertionError"],
            lint_errors=[],
            raw_pytest_output="1 failed, 4 passed",
            raw_lint_output="",
            success=False,
        )

        res = gate.check(mock_failing_result, run_id="run-reg-2")
        assert res.passed is False
        assert len(res.regressions) >= 1
        assert "FAILED" in res.render()

        event_types = [e["event_type"] for e in events]
        assert EventType.REGRESSION_GATE_FAILED.value in event_types


# ===========================================================================
# P3.4 & P3.6: DevOps Agent & Release Notes Tests
# ===========================================================================

class TestDevOpsAgent:
    def test_open_pull_request_with_passing_gate(
        self, sample_ticket: Ticket, dummy_design_spec: DesignSpec
    ):
        events = []
        devops = DevOpsAgent(event_callback=events.append)

        reg_result = RegressionGateResult(
            passed=True,
            baseline_passed=5,
            current_passed=5,
            current_failed=0,
            summary="All tests passed",
        )

        pr = devops.open_pull_request(
            ticket=sample_ticket,
            design_spec=dummy_design_spec,
            diff="--- a/demo_target/app.py\n+++ b/demo_target/app.py\n@@ ...",
            run_id="run-devops-1",
            regression_result=reg_result,
        )

        assert isinstance(pr, PullRequest)
        assert pr.status == "open"
        assert pr.branch == "ma-set/demo-001"
        assert sample_ticket.id in pr.title
        assert "Human-Only Merge Required" in pr.body

        opened_events = [e for e in events if e["event_type"] == EventType.PR_OPENED.value]
        assert len(opened_events) == 1
        assert opened_events[0]["payload"]["pr_number"] == pr.number

    def test_open_pull_request_blocked_by_regression_gate(
        self, sample_ticket: Ticket, dummy_design_spec: DesignSpec
    ):
        devops = DevOpsAgent()
        failing_gate = RegressionGateResult(
            passed=False,
            baseline_passed=5,
            current_passed=4,
            current_failed=1,
            summary="Regression detected in test_signup",
        )

        with pytest.raises(RegressionError, match="Regression gate failed"):
            devops.open_pull_request(
                ticket=sample_ticket,
                design_spec=dummy_design_spec,
                diff="some diff",
                run_id="run-devops-blocked",
                regression_result=failing_gate,
            )

    def test_generate_release_notes(
        self, sample_ticket: Ticket, dummy_design_spec: DesignSpec
    ):
        events = []
        devops = DevOpsAgent(event_callback=events.append)

        rn = devops.generate_release_notes(
            ticket=sample_ticket,
            design_spec=dummy_design_spec,
            diff="some diff",
            run_id="run-rn-1",
            version="v1.2.0",
        )

        assert isinstance(rn, ReleaseNotes)
        assert rn.version == "v1.2.0"
        assert sample_ticket.title in rn.title
        assert "## Key Changes" in rn.markdown
        assert "demo_target/app.py" in rn.changed_files

        rn_events = [e for e in events if e["event_type"] == EventType.RELEASE_NOTES.value]
        assert len(rn_events) == 1
        assert rn_events[0]["payload"]["version"] == "v1.2.0"


# ===========================================================================
# P3.5: Human-Only Merge Enforcement Tests
# ===========================================================================

class TestHumanOnlyMergeEnforcement:
    def test_agent_cannot_merge_pr(self):
        events = []
        devops = DevOpsAgent(event_callback=events.append)

        with pytest.raises(PermissionError) as exc_info:
            devops.merge_pull_request(pr_number=101, run_id="run-merge-test")

        assert "HUMAN-ONLY MERGE ENFORCED" in str(exc_info.value)

        # Verify audit trail event
        blocked_events = [e for e in events if e["event_type"] == EventType.MERGE_ATTEMPT_BLOCKED.value]
        assert len(blocked_events) == 1
        assert blocked_events[0]["payload"]["pr_number"] == 101


# ===========================================================================
# P3.7: Feedback Loop FB3 Tests
# ===========================================================================

class TestFeedbackLoopFB3:
    def test_convert_feedback_text_into_intake_ticket(self, tmp_path: Path):
        events = []
        converter = FeedbackConverter(intake_dir=tmp_path, event_callback=events.append)

        item = FeedbackItem(
            source="user_reports.md",
            content="Bug: /signup endpoint rejects email addresses with '+' character.\n"
                    "Users with user+tag@domain.com are unable to create accounts.",
            reported_by="qa-team",
            severity="high",
        )

        ticket = converter.convert_feedback(item, run_id="run-fb3-1", ticket_id="FB-101")
        assert ticket.id == "FB-101"
        assert ticket.type == TicketType.BUG
        assert ticket.priority == TicketPriority.HIGH
        assert len(ticket.acceptance_criteria) > 0

        # Verify file written to intake queue
        intake = TicketIntake()
        loaded = intake.load_ticket(tmp_path / "fb-101.yaml")
        assert loaded.id == "FB-101"
        assert "user+tag@domain.com" in loaded.description

        # Verify audit events
        event_types = [e["event_type"] for e in events]
        assert EventType.FEEDBACK_INGESTED.value in event_types
        assert EventType.FEEDBACK_CONVERTED.value in event_types

    def test_convert_feedback_from_file(self, tmp_path: Path):
        feedback_file = tmp_path / "incident_report.txt"
        feedback_file.write_text(
            "Critical crash in payment webhook processing\nNullPointerException when payload is empty"
        )

        converter = FeedbackConverter(intake_dir=tmp_path / "queue")
        ticket = converter.convert_feedback_file(feedback_file, ticket_id="INC-001")
        assert ticket.id == "INC-001"
        assert ticket.priority == TicketPriority.CRITICAL
        assert (tmp_path / "queue" / "inc-001.yaml").exists()


# ===========================================================================
# End-to-End Intake to Delivery Flow
# ===========================================================================

class TestEndToEndIntakeToDelivery:
    def test_complete_phase3_flow(self, tmp_path: Path, stub_adapter: ModelAdapter):
        events = []

        # 1. Intake
        intake = TicketIntake(event_callback=events.append)
        ticket_path = tmp_path / "demo_ticket.yaml"
        ticket_path.write_text("""
id: DEMO-001
title: Add input validation to /signup
description: Need validation for signup route to return 400 when missing fields.
type: bug
priority: high
acceptance_criteria:
  - Missing email returns 400
  - Missing password returns 400
""")
        ticket = intake.load_ticket(ticket_path, run_id="e2e-run")

        # 2. Planner
        planner = PlannerAgent(adapter=stub_adapter, event_callback=events.append)
        plan = planner.plan(ticket, run_id="e2e-run")
        assert plan.ticket_id == "DEMO-001"

        # 3. Simulate successful Architect / Dev / Test outcome
        spec = DesignSpec(
            task_summary=plan.title,
            approach="Add validator in app.py",
            files_to_modify=["demo_target/app.py"],
            files_protected=["demo_target/legacy_billing.py"],
            acceptance_criteria=plan.acceptance_criteria,
            impact_report=ImpactReport(
                files_to_modify=["demo_target/app.py"],
                files_to_read=[],
                protected_files_touched=[],
                symbols_changed=["signup"],
                summary="safe changes",
            ),
        )

        # 4. Regression Gate
        reg_gate = RegressionGate(baseline_passed_count=3, event_callback=events.append)
        mock_test_res = TesterResult(
            tests_total=4,
            tests_passed=4,
            tests_failed=0,
            tests_xfailed=0,
            defect_list=[],
            lint_errors=[],
            raw_pytest_output="4 passed",
            raw_lint_output="",
            success=True,
        )
        gate_res = reg_gate.check(mock_test_res, run_id="e2e-run")
        assert gate_res.passed is True

        # 5. DevOps PR & Release Notes
        devops = DevOpsAgent(event_callback=events.append)
        pr = devops.open_pull_request(
            ticket=ticket,
            design_spec=spec,
            diff="+ validation code",
            run_id="e2e-run",
            regression_result=gate_res,
        )
        assert pr.status == "open"

        rn = devops.generate_release_notes(
            ticket=ticket,
            design_spec=spec,
            diff="+ validation code",
            run_id="e2e-run",
        )
        assert "Release" in rn.title

        # 6. Safety check: Agent cannot merge
        with pytest.raises(PermissionError):
            devops.merge_pull_request(pr.number, run_id="e2e-run")

        # 7. Post-release feedback arrives (FB3)
        converter = FeedbackConverter(intake_dir=tmp_path / "intake", event_callback=events.append)
        new_ticket = converter.convert_feedback(
            FeedbackItem(
                source="post_release_report.txt",
                content="Feature request: Add rate limiting to /signup endpoint",
                severity="medium",
            ),
            run_id="e2e-run",
        )
        assert new_ticket.type == TicketType.FEATURE
        assert (tmp_path / "intake" / f"{new_ticket.id.lower()}.yaml").exists()

        # Check sequence of events
        types = [e["event_type"] for e in events]
        assert EventType.TICKET_INGESTED.value in types
        assert EventType.PLAN_PRODUCED.value in types
        assert EventType.REGRESSION_GATE_PASSED.value in types
        assert EventType.PR_OPENED.value in types
        assert EventType.RELEASE_NOTES.value in types
        assert EventType.MERGE_ATTEMPT_BLOCKED.value in types
        assert EventType.FEEDBACK_CONVERTED.value in types
