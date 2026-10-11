"""
P4.1, P4.2, P4.4 — Orchestration State & Escalation
====================================================
Defines shared state across the LangGraph orchestration graph (Node A6)
and the escalation report generator when runs fail or hit budget caps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    """
    Shared state across the LangGraph orchestration graph.
    All nodes read and update this state dictionary.
    """

    # Identifiers & Lifecycle
    run_id: str
    status: str  # "running" | "completed" | "escalated" | "budget_exceeded"
    start_time: str
    end_time: str

    # Ticket & Planning (A1)
    ticket: Dict[str, Any]
    plan: Optional[Dict[str, Any]]

    # Architecture & Sign-Off (A2)
    design_spec: Optional[Dict[str, Any]]
    gate_approved: bool
    gate_feedback: str

    # Implementation & Testing (A3, A4 - FB1)
    developer_diff: str
    developer_patched: bool
    developer_patched_contents: Dict[str, str]
    tester_success: bool
    tester_defect_list: List[str]
    tests_passed: int
    tests_failed: int
    fb1_retries: int

    # Review (A4 - FB2)
    reviewer_approved: bool
    reviewer_feedback: List[str]
    fb2_retries: int

    # Delivery & Gates (A5)
    regression_passed: bool
    pr: Optional[Dict[str, Any]]
    release_notes: Optional[Dict[str, Any]]

    # Governance & Budget Caps (A6)
    llm_calls_used: int
    max_llm_calls: int
    max_retries: int
    budget_exceeded: bool

    # Escalation
    escalation_reason: Optional[str]
    escalation_report: Optional[str]
    failing_node: Optional[str]


@dataclass
class EscalationReport:
    """P4.4 — Human-readable escalation report for engineering leads."""

    run_id: str
    ticket_id: str
    failing_node: str
    reason: str
    fb1_retries: int
    fb2_retries: int
    llm_calls_used: int
    max_llm_calls: int
    defects: List[str] = field(default_factory=list)
    review_feedback: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def render(self) -> str:
        lines = [
            "=" * 60,
            "MA-SET PIPELINE ESCALATION REPORT",
            "=" * 60,
            f"Run ID:         {self.run_id}",
            f"Ticket:         {self.ticket_id}",
            f"Failing Node:   {self.failing_node}",
            f"Timestamp:      {self.created_at}",
            "",
            "ESCALATION REASON:",
            f"  {self.reason}",
            "",
            "GOVERNANCE COUNTERS:",
            f"  - FB1 Retries (Dev/Test):     {self.fb1_retries}",
            f"  - FB2 Retries (Arch/Review):  {self.fb2_retries}",
            f"  - LLM Calls Used / Cap:       {self.llm_calls_used} / {self.max_llm_calls}",
        ]

        if self.defects:
            lines.extend([
                "",
                "UNRESOLVED DEFECTS:",
            ])
            for d in self.defects:
                lines.append(f"  - [DEFECT] {d}")

        if self.review_feedback:
            lines.extend([
                "",
                "REVIEW CRITIQUES:",
            ])
            for rf in self.review_feedback:
                lines.append(f"  - [CRITIQUE] {rf}")

        lines.extend([
            "",
            "RECOMMENDED ACTION FOR HUMAN REVIEWER:",
            "  1. Review the generated audit trail at runs/{run_id}.jsonl",
            "  2. Check whether the ticket requirements or test fixtures are contradictory",
            "  3. Intervene manually or adjust the budget cap before re-triggering.",
            "=" * 60,
        ])
        return "\n".join(lines)
