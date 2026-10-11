"""
P3.7 — Post-Release Feedback Loop (FB3)
========================================
Node A5 -> Node A1:
Converts post-release feedback (user bug reports, production incidents, QA notes)
into a structured, prioritized ticket in the intake queue.

Closes the IDEF0 Feedback Loop FB3:
  Delivery / Monitoring (A5) -> Planning & Intake (A1)

Events emitted:
  FEEDBACK_INGESTED
  FEEDBACK_CONVERTED
  TICKET_INGESTED
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.events.schema import Event, EventType
from ma_set.model.adapter import ModelAdapter
from ma_set.tools.ticket_intake import Ticket, TicketIntake, TicketPriority, TicketType


@dataclass
class FeedbackItem:
    """Raw feedback content from users, testers, or production telemetry."""

    source: str
    content: str
    reported_by: Optional[str] = None
    severity: str = "medium"


class FeedbackConverter:
    """
    Converts raw feedback into structured tickets and deposits them into
    the ticket intake queue (Feedback Loop FB3).
    """

    def __init__(
        self,
        intake_dir: Path | str,
        adapter: Optional[ModelAdapter] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A5",
        agent: str = "feedback_converter",
    ):
        self._intake_dir = Path(intake_dir).resolve()
        self._adapter = adapter
        self._callback = event_callback
        self._node = node
        self._agent = agent
        self._intake = TicketIntake(event_callback=event_callback, node="A1")

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

    def convert_feedback_file(
        self,
        feedback_file: Path | str,
        run_id: str = "system",
        ticket_id: Optional[str] = None,
    ) -> Ticket:
        """
        Read a feedback file (markdown, text, or json) and convert to a ticket.
        """
        path = Path(feedback_file).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Feedback file not found: {path}")

        raw_text = path.read_text(encoding="utf-8")
        item = FeedbackItem(
            source=str(path.name),
            content=raw_text,
            reported_by="post-release-telemetry",
            severity="high" if "critical" in raw_text.lower() or "error" in raw_text.lower() else "medium",
        )
        return self.convert_feedback(item, run_id=run_id, ticket_id=ticket_id)

    def convert_feedback(
        self,
        item: FeedbackItem,
        run_id: str = "system",
        ticket_id: Optional[str] = None,
    ) -> Ticket:
        """
        Transform a FeedbackItem into a new Ticket and write it to the intake directory.
        """
        self._emit(
            EventType.FEEDBACK_INGESTED,
            run_id=run_id,
            payload={
                "source": item.source,
                "severity": item.severity,
                "reported_by": item.reported_by,
                "length": len(item.content),
            },
        )

        tid = ticket_id or f"FB-{uuid.uuid4().hex[:6].upper()}"

        # Parse title and description
        lines = [line.strip() for line in item.content.splitlines() if line.strip()]
        title = lines[0].lstrip("#").strip() if lines else "Feedback Report"
        if len(title) > 80:
            title = title[:77] + "..."

        description = item.content.strip()

        # Infer priority
        sev_lower = (item.severity or "").lower()
        content_lower = item.content.lower()
        if "crit" in sev_lower or "critical" in content_lower or "security" in content_lower or "crash" in content_lower:
            priority = TicketPriority.CRITICAL
        elif "high" in sev_lower or "urgent" in content_lower:
            priority = TicketPriority.HIGH
        elif "low" in sev_lower:
            priority = TicketPriority.LOW
        else:
            priority = TicketPriority.MEDIUM

        # Infer ticket type
        if "feature" in content_lower or "enhancement" in content_lower or "suggestion" in content_lower:
            ttype = TicketType.FEATURE
        else:
            ttype = TicketType.BUG

        # Acceptance criteria
        acceptance_criteria = [
            f"Fix issue reported in {item.source}: {title}",
            "Add regression test reproducing the reported behavior",
            "Verify all existing test suites pass",
        ]

        ticket = Ticket(
            id=tid,
            title=title,
            description=description,
            type=ttype,
            priority=priority,
            acceptance_criteria=acceptance_criteria,
            labels=["feedback-loop", "fb3", item.source],
            author=item.reported_by or "feedback-agent",
            metadata={"source_file": item.source, "origin": "FB3"},
        )

        # Write ticket into intake directory
        saved_path = self._intake.save_ticket(ticket, self._intake_dir)

        self._emit(
            EventType.FEEDBACK_CONVERTED,
            run_id=run_id,
            payload={
                "ticket_id": ticket.id,
                "title": ticket.title,
                "priority": ticket.priority,
                "target_file": str(saved_path),
            },
        )

        return ticket
