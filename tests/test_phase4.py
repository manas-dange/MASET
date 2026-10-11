"""
Phase 4 Tests — Orchestration, Governance & Benchmark (P4.1–P4.6)
==================================================================
Covers:
  - P4.1: LangGraph Orchestration Graph (wires A1 to A5 with shared state)
  - P4.2: Budget & Retry Caps (enforces max LLM calls, max 3 retries per loop)
  - P4.3: Audit Trail Persistence (verifies events in runs/{run_id}.jsonl and replay)
  - P4.4: Escalation Handling (produces human-readable EscalationReport on failure)
  - P4.5: Benchmark Task Set (validates 10 benchmark tickets and 2 traps)
  - P4.6: Benchmark Runner & Reporting (runs suite, aggregates metrics, renders markdown)
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from ma_set.agents.gate import GateMode
from ma_set.benchmark.runner import BenchmarkReport, BenchmarkRunner
from ma_set.benchmark.tasks import BENCHMARK_TASKS
from ma_set.events.log import EventLog
from ma_set.events.schema import EventType
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider
from ma_set.orchestration.graph import PipelineOrchestrator, PipelineResult
from ma_set.orchestration.state import EscalationReport
from ma_set.tools.ticket_intake import Ticket, TicketPriority, TicketType


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def stub_adapter() -> ModelAdapter:
    return ModelAdapter(ModelConfig(provider=Provider.STUB))


@pytest.fixture
def sample_ticket() -> Ticket:
    return Ticket(
        id="DEMO-001",
        title="Add input validation to /signup endpoint",
        description="Validate email and password fields on /signup, returning 400 on error.",
        type=TicketType.BUG,
        priority=TicketPriority.HIGH,
        acceptance_criteria=[
            "POST /signup with missing email returns 400",
            "POST /signup with valid payload returns 201",
        ],
    )


# ===========================================================================
# P4.1: Orchestration Graph Tests
# ===========================================================================

class TestOrchestrationGraph:
    def test_end_to_end_orchestration_run_succeeds(
        self, sample_ticket: Ticket, stub_adapter: ModelAdapter, tmp_path: Path
    ):
        orchestrator = PipelineOrchestrator(
            adapter=stub_adapter,
            log_dir=tmp_path / "runs",
            gate_mode=GateMode.AUTO_APPROVE,
        )

        res: PipelineResult = orchestrator.run(sample_ticket, run_id="orch-test-01")

        assert res.success is True
        assert res.status == "completed"
        assert res.plan is not None
        assert res.plan.ticket_id == sample_ticket.id
        assert res.pr is not None
        assert res.pr.status == "open"
        assert res.release_notes is not None
        assert "Release" in res.release_notes.title

    def test_orchestration_escalates_on_rejected_gate(
        self, sample_ticket: Ticket, stub_adapter: ModelAdapter, tmp_path: Path
    ):
        orchestrator = PipelineOrchestrator(
            adapter=stub_adapter,
            log_dir=tmp_path / "runs",
            gate_mode=GateMode.AUTO_REJECT,
        )

        res: PipelineResult = orchestrator.run(sample_ticket, run_id="orch-test-reject")

        assert res.success is False
        assert res.status == "escalated"
        assert res.pr is None
        assert res.escalation_report is not None
        assert "Human design sign-off rejected" in res.escalation_report.reason


# ===========================================================================
# P4.2: Budget & Retry Caps Tests
# ===========================================================================

class TestGovernanceCaps:
    def test_budget_cap_stops_run_cleanly(
        self, sample_ticket: Ticket, stub_adapter: ModelAdapter, tmp_path: Path
    ):
        # Set max LLM calls to 0 so it immediately breaches budget
        orchestrator = PipelineOrchestrator(
            adapter=stub_adapter,
            max_llm_calls=0,
            log_dir=tmp_path / "runs",
        )

        res: PipelineResult = orchestrator.run(sample_ticket, run_id="budget-cap-test")

        assert res.success is False
        assert res.status == "escalated"
        assert res.escalation_report is not None
        assert "Budget cap exceeded" in res.escalation_report.reason

    def test_retry_caps_configured(self, stub_adapter: ModelAdapter):
        orchestrator = PipelineOrchestrator(adapter=stub_adapter, max_retries=3)
        assert orchestrator.max_retries == 3
        assert orchestrator.max_llm_calls > 0


# ===========================================================================
# P4.3: Audit Trail Persistence & Replay Tests
# ===========================================================================

class TestAuditTrailPersistence:
    def test_audit_trail_saved_and_replayed(
        self, sample_ticket: Ticket, stub_adapter: ModelAdapter, tmp_path: Path
    ):
        log_dir = tmp_path / "runs"
        orchestrator = PipelineOrchestrator(
            adapter=stub_adapter,
            log_dir=log_dir,
            gate_mode=GateMode.AUTO_APPROVE,
        )

        res = orchestrator.run(sample_ticket, run_id="audit-run-99")
        log_file = log_dir / "audit-run-99.jsonl"

        assert log_file.exists()
        assert log_file.stat().st_size > 0

        # Replay events
        event_log = EventLog(run_id="audit-run-99", log_dir=log_dir)
        events = list(event_log.replay())

        event_types = [e.get("event_type") for e in events]
        assert EventType.RUN_STARTED.value in event_types
        assert EventType.AGENT_STARTED.value in event_types
        assert EventType.PR_OPENED.value in event_types
        assert EventType.RUN_FINISHED.value in event_types


# ===========================================================================
# P4.4: Escalation Handling Tests
# ===========================================================================

class TestEscalationHandling:
    def test_escalation_report_rendering(self):
        report = EscalationReport(
            run_id="esc-001",
            ticket_id="TICK-555",
            failing_node="A4:tester",
            reason="FB1 retry limit exceeded (3 attempts)",
            fb1_retries=3,
            fb2_retries=1,
            llm_calls_used=8,
            max_llm_calls=15,
            defects=["test_signup FAILED - AssertionError"],
            review_feedback=["Approach violated architecture boundary"],
        )

        rendered = report.render()
        assert "ESCALATION REPORT" in rendered
        assert "TICK-555" in rendered
        assert "A4:tester" in rendered
        assert "FB1 Retries (Dev/Test):     3" in rendered
        assert "test_signup FAILED" in rendered
        assert "RECOMMENDED ACTION" in rendered


# ===========================================================================
# P4.5: Benchmark Task Set Tests
# ===========================================================================

class TestBenchmarkTaskSet:
    def test_benchmark_has_10_tasks(self):
        assert len(BENCHMARK_TASKS) == 10

    def test_benchmark_contains_at_least_two_traps(self):
        traps = [t for t in BENCHMARK_TASKS if t.metadata.get("is_trap") is True]
        assert len(traps) >= 2
        for trap in traps:
            assert "legacy_billing.py" in trap.metadata.get("target_file", "")
            assert "TRAP" in trap.title

    def test_benchmark_tasks_valid_tickets(self):
        ids = set()
        for t in BENCHMARK_TASKS:
            assert t.id not in ids, f"Duplicate task id: {t.id}"
            ids.add(t.id)
            assert t.title
            assert t.priority in [TicketPriority.LOW, TicketPriority.MEDIUM, TicketPriority.HIGH, TicketPriority.CRITICAL]


# ===========================================================================
# P4.6: Benchmark Runner & Reporting Tests
# ===========================================================================

class TestBenchmarkRunner:
    def test_benchmark_runner_executes_suite(self, stub_adapter: ModelAdapter, tmp_path: Path):
        # Run a 3-task subset for fast test execution (1 feature, 1 trap, 1 vague)
        subset_tasks = [
            BENCHMARK_TASKS[0],  # BENCH-001
            BENCHMARK_TASKS[5],  # BENCH-006 (Trap 1)
            BENCHMARK_TASKS[9],  # BENCH-010 (Vague)
        ]

        orchestrator = PipelineOrchestrator(
            adapter=stub_adapter,
            log_dir=tmp_path / "runs",
            gate_mode=GateMode.AUTO_APPROVE,
        )

        runner = BenchmarkRunner(orchestrator=orchestrator, tasks=subset_tasks)
        report: BenchmarkReport = runner.run_suite()

        assert isinstance(report, BenchmarkReport)
        assert report.total_tasks == 3
        assert report.traps_attempted == 1
        assert report.traps_blocked == 1
        assert report.trap_containment_rate == 100.0

        # Markdown rendering check
        md = report.render_markdown()
        assert "# MA-SET Benchmark Evaluation Report" in md
        assert "BENCH-001" in md
        assert "BENCH-006" in md
        assert "100.0%" in md
