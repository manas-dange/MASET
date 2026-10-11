"""
P3.1 — Ticket Intake
====================
Reads and validates software engineering tickets from YAML (or JSON) files.
Acts as Node A1's intake mechanism.

Schema:
  id:                  Unique ticket identifier (e.g. DEMO-001)
  title:               Short description of feature/bug
  description:         Detailed problem statement or feature requirement
  type:                bug | feature | refactor | task
  priority:            low | medium | high | critical
  acceptance_criteria: List of testable conditions
  labels:              List of string tags
  author:              Creator/reporter (optional)
  status:              open | in_progress | closed
  metadata:            Arbitrary key-value store
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ma_set.events.schema import Event, EventType


class TicketType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TASK = "task"


class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Ticket(BaseModel):
    """Structured representation of a software engineering ticket."""

    id: str = Field(description="Unique ticket identifier")
    title: str = Field(description="Short summary of the task")
    description: str = Field(default="", description="Detailed explanation")
    type: TicketType = Field(default=TicketType.BUG, description="Ticket classification")
    priority: TicketPriority = Field(default=TicketPriority.MEDIUM, description="Urgency")
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="List of verifiable acceptance criteria"
    )
    labels: List[str] = Field(default_factory=list, description="Categorization tags")
    author: Optional[str] = Field(default=None, description="Submitter identifier")
    status: str = Field(default="open", description="Lifecycle status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata")
    file_path: Optional[str] = Field(default=None, description="Original source path if loaded from disk")

    model_config = ConfigDict(use_enum_values=True)

    def is_vague(self) -> bool:
        """Returns True if the ticket lacks essential details or acceptance criteria."""
        if not self.acceptance_criteria:
            return True
        if len(self.description.strip()) < 30:
            return True
        return False

    def to_yaml(self) -> str:
        """Serialize ticket to YAML formatted string."""
        data = self.model_dump(exclude={"file_path"}, exclude_none=True)
        return yaml.dump(data, sort_keys=False, default_flow_style=False)

    @classmethod
    def from_yaml(cls, yaml_content: str, source_path: Optional[str] = None) -> "Ticket":
        """Parse and validate ticket from YAML string."""
        raw_data = yaml.safe_load(yaml_content)
        if not isinstance(raw_data, dict):
            raise ValueError(f"Expected YAML dictionary, got {type(raw_data)}")
        ticket = cls(**raw_data)
        ticket.file_path = source_path
        return ticket


class TicketIntake:
    """
    Intake manager that reads, validates, and stores tickets.
    Emits TICKET_INGESTED events to the audit trail.
    """

    def __init__(
        self,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A1",
        agent: str = "ticket_intake",
    ):
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

    @classmethod
    def load_file(cls, path: Path | str) -> Ticket:
        """Convenience loader from file without logging callbacks."""
        file_path = Path(path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Ticket file not found: {file_path}")
        content = file_path.read_text(encoding="utf-8")
        return Ticket.from_yaml(content, source_path=str(file_path))

    @classmethod
    def load_string(cls, content: str) -> Ticket:
        """Convenience loader from string without logging callbacks."""
        return Ticket.from_yaml(content)

    def load_ticket(self, path: Path | str, run_id: str = "system") -> Ticket:
        """Load a single ticket from a YAML file."""
        file_path = Path(path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Ticket file not found: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        ticket = Ticket.from_yaml(content, source_path=str(file_path))

        self._emit(
            EventType.TICKET_INGESTED,
            run_id=run_id,
            payload={
                "ticket_id": ticket.id,
                "title": ticket.title,
                "type": ticket.type,
                "priority": ticket.priority,
                "file_path": str(file_path),
                "is_vague": ticket.is_vague(),
            },
        )
        return ticket

    def load_tickets_from_dir(self, dir_path: Path | str, run_id: str = "system") -> List[Ticket]:
        """Load and sort all YAML tickets in a directory."""
        directory = Path(dir_path).resolve()
        if not directory.exists() or not directory.is_dir():
            return []

        tickets: List[Ticket] = []
        for p in sorted(directory.glob("*.y*ml")):
            try:
                ticket = self.load_ticket(p, run_id=run_id)
                tickets.append(ticket)
            except Exception:
                continue

        # Priority order: critical > high > medium > low
        priority_order = {
            TicketPriority.CRITICAL.value: 0,
            TicketPriority.HIGH.value: 1,
            TicketPriority.MEDIUM.value: 2,
            TicketPriority.LOW.value: 3,
        }
        tickets.sort(key=lambda t: priority_order.get(t.priority, 99))
        return tickets

    def save_ticket(self, ticket: Ticket, dest_dir: Path | str) -> Path:
        """Write ticket as a YAML file in the destination directory."""
        dest = Path(dest_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        filename = f"{ticket.id.lower().replace(' ', '_')}.yaml"
        target_path = dest / filename
        target_path.write_text(ticket.to_yaml(), encoding="utf-8")
        ticket.file_path = str(target_path)
        return target_path
