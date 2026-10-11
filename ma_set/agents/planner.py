"""
P3.2 — Planner Agent with Ticket Refinement
============================================
Node A1: Ingests tickets, clarifies vague requirements (Section 5.3 refinement),
derives user stories, technical tasks, and concrete acceptance criteria.

Produces a structured PlanResult whose `formatted_breakdown` feeds directly
into the Architect agent (Node A2).

Events emitted:
  AGENT_STARTED
  TICKET_REFINED (if ticket was vague and refined)
  PLAN_PRODUCED
  AGENT_FINISHED
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ma_set.events.schema import Event, EventType
from ma_set.model.adapter import ModelAdapter
from ma_set.tools.ticket_intake import Ticket


@dataclass
class PlanResult:
    """Structured plan produced by the Planner agent."""

    ticket_id: str
    title: str
    summary: str
    user_stories: List[str]
    tasks: List[str]
    acceptance_criteria: List[str]
    was_refined: bool = False
    refinement_notes: Optional[str] = None
    raw_llm_output: str = ""

    @property
    def formatted_breakdown(self) -> str:
        """Text format consumed by ArchitectAgent."""
        lines = [
            f"TICKET: {self.ticket_id} - {self.title}",
            f"SUMMARY: {self.summary}",
            "",
            "USER STORIES:",
        ]
        for us in self.user_stories:
            lines.append(f"  * {us}")
        lines.append("")
        lines.append("TECHNICAL TASKS:")
        for idx, task in enumerate(self.tasks, 1):
            lines.append(f"  {idx}. {task}")
        lines.append("")
        lines.append("ACCEPTANCE CRITERIA:")
        for ac in self.acceptance_criteria:
            lines.append(f"  - {ac}")
        if self.refinement_notes:
            lines.append("")
            lines.append(f"REFINEMENT NOTES: {self.refinement_notes}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stub Plan for DEMO-001 (or default fallback)
# ---------------------------------------------------------------------------

_STUB_DEMO_PLAN = PlanResult(
    ticket_id="DEMO-001",
    title="Add input validation to /signup endpoint",
    summary="Ensure /signup validates required email and password fields, returning HTTP 400 on error without regressing existing behaviour.",
    user_stories=[
        "As an API consumer, I receive an HTTP 400 Bad Request if I submit a signup payload missing 'email' or 'password'.",
        "As an API consumer, I continue to receive HTTP 201 Created when submitting valid signup data.",
        "As an existing customer, my legacy billing account records remain completely unaffected.",
    ],
    tasks=[
        "Inspect demo_target/app.py and locate the signup() route handler.",
        "Implement request validation helper validate_signup(payload) returning 400 on missing or empty email/password.",
        "Ensure all existing baseline tests pass and xfail validation tests turn green.",
        "Verify demo_target/legacy_billing.py is not modified.",
    ],
    acceptance_criteria=[
        "POST /signup with missing email returns 400 and JSON error",
        "POST /signup with missing password returns 400 and JSON error",
        "POST /signup with empty body returns 400",
        "POST /signup with valid payload returns 201 and created user",
        "demo_target/legacy_billing.py remains untouched",
    ],
    was_refined=True,
    refinement_notes="Vague ticket requirements enriched with explicit HTTP status codes, edge cases, and safety constraints.",
)


class PlannerAgent:
    """
    Planner Agent (Node A1).
    Transforms tickets into technical task breakdowns and refines vague requirements.
    """

    SYSTEM_PROMPT = textwrap.dedent("""\
        You are the Planner Agent (Node A1) in the MA-SET multi-agent software engineering team.
        Your responsibility is to analyze software engineering tickets, clarify ambiguities,
        break them down into user stories, technical tasks, and clear acceptance criteria.

        Format your response as a valid JSON object with the following keys:
        {
          "summary": "1-2 sentence executive summary of the work",
          "was_refined": true/false (true if the ticket was vague or missing acceptance criteria),
          "refinement_notes": "Explanation of ambiguities resolved or edge cases added",
          "user_stories": [
            "As a [role], I want [feature] so that [benefit]"
          ],
          "tasks": [
            "1. Technical implementation step...",
            "2. Next step..."
          ],
          "acceptance_criteria": [
            "- Condition that must be verified"
          ]
        }
        Return ONLY valid JSON.
    """)

    def __init__(
        self,
        adapter: ModelAdapter,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A1",
        agent: str = "planner",
    ):
        self._adapter = adapter
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

    def plan(
        self,
        ticket: Ticket,
        run_id: str,
        codebase_context: Optional[str] = None,
    ) -> PlanResult:
        """
        Analyze ticket and generate PlanResult.
        Performs ticket refinement if ticket is vague or missing criteria.
        """
        self._emit(
            EventType.AGENT_STARTED,
            run_id=run_id,
            payload={
                "ticket_id": ticket.id,
                "title": ticket.title,
                "priority": ticket.priority,
                "is_vague": ticket.is_vague(),
            },
        )

        is_vague = ticket.is_vague()

        if self._adapter.is_stub:
            # Stub mode
            if ticket.id == "DEMO-001" or "signup" in ticket.title.lower():
                plan_res = _STUB_DEMO_PLAN
            else:
                user_stories = [
                    f"As a user, I want {ticket.title} so that the system behaves as expected."
                ]
                tasks = [
                    f"Analyze requirements for {ticket.title}",
                    f"Implement changes for {ticket.id}",
                    "Run regression tests and verify all checks pass",
                ]
                criteria = (
                    ticket.acceptance_criteria
                    if ticket.acceptance_criteria
                    else [f"{ticket.title} functions correctly without regression"]
                )
                plan_res = PlanResult(
                    ticket_id=ticket.id,
                    title=ticket.title,
                    summary=ticket.description or ticket.title,
                    user_stories=user_stories,
                    tasks=tasks,
                    acceptance_criteria=criteria,
                    was_refined=is_vague,
                    refinement_notes="Auto-refined missing acceptance criteria" if is_vague else None,
                )
            
            # Emit stub response via adapter to register llm_stub_response
            self._adapter.complete(
                prompt=f"Plan ticket {ticket.id}: {ticket.title}",
                node=self._node,
                agent=self._agent,
                run_id=run_id,
            )
        else:
            # LLM mode
            user_prompt = (
                f"TICKET DETAILS:\n"
                f"ID: {ticket.id}\n"
                f"Title: {ticket.title}\n"
                f"Type: {ticket.type}\n"
                f"Priority: {ticket.priority}\n"
                f"Description:\n{ticket.description}\n"
                f"Existing Acceptance Criteria: {ticket.acceptance_criteria}\n"
            )
            if codebase_context:
                user_prompt += f"\nCODEBASE CONTEXT:\n{codebase_context}\n"

            resp = self._adapter.complete(
                prompt=user_prompt,
                system_prompt=self.SYSTEM_PROMPT,
                node=self._node,
                agent=self._agent,
                run_id=run_id,
            )

            content_text = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
            plan_res = self._parse_llm_response(ticket, content_text)

        if plan_res.was_refined:
            self._emit(
                EventType.TICKET_REFINED,
                run_id=run_id,
                payload={
                    "ticket_id": ticket.id,
                    "refinement_notes": plan_res.refinement_notes,
                    "acceptance_criteria_count": len(plan_res.acceptance_criteria),
                    "user_stories_count": len(plan_res.user_stories),
                },
            )

        self._emit(
            EventType.PLAN_PRODUCED,
            run_id=run_id,
            payload={
                "ticket_id": ticket.id,
                "summary": plan_res.summary,
                "task_count": len(plan_res.tasks),
                "acceptance_criteria": plan_res.acceptance_criteria,
            },
        )

        self._emit(
            EventType.AGENT_FINISHED,
            run_id=run_id,
            payload={"ticket_id": ticket.id, "was_refined": plan_res.was_refined},
        )

        return plan_res

    def _parse_llm_response(self, ticket: Ticket, content: str) -> PlanResult:
        """Parse structured JSON from model completion."""
        # Try finding JSON block
        clean_text = content.strip()
        json_match = re.search(r"\{.*\}", clean_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                return PlanResult(
                    ticket_id=ticket.id,
                    title=ticket.title,
                    summary=data.get("summary", ticket.title),
                    user_stories=data.get("user_stories", []),
                    tasks=data.get("tasks", []),
                    acceptance_criteria=data.get("acceptance_criteria", ticket.acceptance_criteria),
                    was_refined=data.get("was_refined", ticket.is_vague()),
                    refinement_notes=data.get("refinement_notes"),
                    raw_llm_output=content,
                )
            except Exception:
                pass

        # Fallback if model returned unstructured text
        return PlanResult(
            ticket_id=ticket.id,
            title=ticket.title,
            summary=clean_text[:200],
            user_stories=[f"As a user, I want {ticket.title}"],
            tasks=[line.strip() for line in clean_text.splitlines() if line.strip()][:5],
            acceptance_criteria=ticket.acceptance_criteria or ["Verify change operates as expected"],
            was_refined=ticket.is_vague(),
            refinement_notes="Parsed from raw completion",
            raw_llm_output=content,
        )
