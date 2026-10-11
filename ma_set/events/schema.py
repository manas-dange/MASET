"""
P0.4 — Event Schema
====================
Defines the structured JSON event schema emitted by every agent, tool, and
protection layer in MA-SET.

Schema fields
-------------
run_id      : str   — UUID4 identifying the current pipeline run
timestamp   : str   — ISO-8601 UTC timestamp (microsecond precision)
node        : str   — IDEF0 node tag  ("A1" .. "A6")
agent       : str   — Which agent or component emitted the event
event_type  : str   — Category of event (see EventType enum)
payload     : dict  — Arbitrary event-specific data
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Event type catalogue
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    # Lifecycle
    RUN_STARTED         = "run_started"
    RUN_FINISHED        = "run_finished"
    RUN_ESCALATED       = "run_escalated"

    # Agent lifecycle
    AGENT_STARTED       = "agent_started"
    AGENT_FINISHED      = "agent_finished"
    AGENT_RETRYING      = "agent_retrying"
    AGENT_ESCALATED     = "agent_escalated"

    # LLM
    LLM_REQUEST         = "llm_request"
    LLM_RESPONSE        = "llm_response"
    LLM_ERROR           = "llm_error"
    LLM_CACHE_HIT       = "llm_cache_hit"
    LLM_STUB_RESPONSE   = "llm_stub_response"

    # Tool calls
    TOOL_CALL           = "tool_call"
    TOOL_RESULT         = "tool_result"

    # Protection layer
    FILE_WRITE_ALLOWED  = "file_write_allowed"
    FILE_WRITE_BLOCKED  = "file_write_blocked"
    SANDBOX_COMMAND     = "sandbox_command"
    SANDBOX_RESULT      = "sandbox_result"

    # Gates
    HUMAN_GATE_OPENED   = "human_gate_opened"
    HUMAN_GATE_APPROVED = "human_gate_approved"
    HUMAN_GATE_REJECTED = "human_gate_rejected"

    # Artifacts
    DIFF_PRODUCED       = "diff_produced"
    TEST_RESULTS        = "test_results"
    REVIEW_VERDICT      = "review_verdict"
    IMPACT_REPORT       = "impact_report"
    DESIGN_SPEC         = "design_spec"
    PR_OPENED           = "pr_opened"
    RELEASE_NOTES       = "release_notes"

    # Phase 3: Intake & Delivery
    TICKET_INGESTED     = "ticket_ingested"
    TICKET_REFINED      = "ticket_refined"
    PLAN_PRODUCED       = "plan_produced"
    REGRESSION_GATE_PASSED = "regression_gate_passed"
    REGRESSION_GATE_FAILED = "regression_gate_failed"
    MERGE_ATTEMPT_BLOCKED  = "merge_attempt_blocked"
    FEEDBACK_INGESTED   = "feedback_ingested"
    FEEDBACK_CONVERTED  = "feedback_converted"

    # Budget
    BUDGET_CHECKED      = "budget_checked"
    BUDGET_EXCEEDED     = "budget_exceeded"

    # MA-SET Lab: Evaluation & Trajectory Events
    TASK_STARTED        = "task_started"
    TASK_COMPLETED      = "task_completed"
    EVALUATION_STARTED  = "evaluation_started"
    EVALUATION_FINISHED = "evaluation_finished"
    FAILURE_DETECTED    = "failure_detected"
    FAILURE_CLASSIFIED  = "failure_classified"
    RECOVERY_STARTED    = "recovery_started"
    RECOVERY_SUCCEEDED  = "recovery_succeeded"
    RECOVERY_FAILED     = "recovery_failed"
    CONSTRAINT_CHECK    = "constraint_check"
    CONSTRAINT_VIOLATION= "constraint_violation"
    QUALITY_SCORE       = "quality_score"
    JUDGE_REQUEST       = "judge_request"
    JUDGE_RESPONSE      = "judge_response"
    TASK_REVIEWED       = "task_reviewed"
    TASK_CALIBRATED     = "task_calibrated"


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

class Event(BaseModel):
    """A single structured event in the MA-SET audit trail."""

    run_id: str = Field(
        description="UUID4 identifying the current pipeline run"
    )
    timestamp: str = Field(
        description="ISO-8601 UTC timestamp with microsecond precision"
    )
    node: str = Field(
        description="IDEF0 node tag (A0-A7, 'system', 'evaluator', 'datasetforge', 'lab')",
        pattern=r"^(A[0-7]|system|evaluator|datasetforge|lab)$"
    )
    agent: str = Field(
        description="Component that emitted the event (e.g. 'planner', 'orchestrator')"
    )
    event_type: EventType = Field(
        description="Category of event"
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary event-specific data"
    )
    sequence: Optional[int] = Field(
        default=None,
        description="Monotonically increasing counter within a run (set by the log writer)"
    )

    model_config = ConfigDict(use_enum_values=True)

    @classmethod
    def make(
        cls,
        *,
        run_id: str,
        node: str,
        agent: str,
        event_type: EventType,
        payload: Optional[Dict[str, Any]] = None,
        sequence: Optional[int] = None,
    ) -> "Event":
        """Convenience constructor that stamps the current UTC time."""
        return cls(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            node=node,
            agent=agent,
            event_type=event_type,
            payload=payload or {},
            sequence=sequence,
        )

    def to_jsonl(self) -> str:
        """Return a compact JSON string terminated by newline (for JSONL logs)."""
        return self.model_dump_json() + "\n"


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

def new_run_id() -> str:
    """Generate a fresh run UUID."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    run_id = new_run_id()
    ev = Event.make(
        run_id=run_id,
        node="A1",
        agent="planner",
        event_type=EventType.AGENT_STARTED,
        payload={"ticket_id": "DEMO-001"},
    )
    print(json.dumps(json.loads(ev.to_jsonl()), indent=2))
