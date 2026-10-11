"""MA-SET Lab: Task Registry.

Central registry for managing, loading, filtering, and querying versioned
benchmark tasks across dataset releases (e.g. datasets/v1.0/).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema, TaskStatus, TaskType
from ma_set.datasetforge.validators.task_validator import TaskValidator
from ma_set.tools.ticket_intake import Ticket, TicketPriority, TicketType


class TaskRegistry:
    """Central repository of versioned benchmark tasks."""

    def __init__(self, dataset_dir: Optional[Path] = None):
        self.dataset_dir = dataset_dir or (Path(__file__).parents[2] / "datasets" / "v1.0")
        self._tasks: Dict[str, BenchmarkTaskSchema] = {}
        self.validator = TaskValidator()
        if self.dataset_dir.exists():
            self.load_from_directory(self.dataset_dir)

    def load_from_directory(self, path: Path) -> int:
        """Load all valid YAML tasks from directory."""
        loaded = 0
        for yml_path in sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml")):
            try:
                with open(yml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and "id" in data:
                    task = BenchmarkTaskSchema(**data)
                    self._tasks[task.id] = task
                    loaded += 1
            except Exception:
                continue
        return loaded

    def register(self, task: BenchmarkTaskSchema) -> None:
        """Add or update a task in the registry."""
        self._tasks[task.id] = task

    def get(self, task_id: str) -> Optional[BenchmarkTaskSchema]:
        """Retrieve task by ID."""
        return self._tasks.get(task_id)

    def list_all(self) -> List[BenchmarkTaskSchema]:
        """List all registered tasks."""
        return list(self._tasks.values())

    def filter(
        self,
        domain: Optional[str] = None,
        task_type: Optional[str] = None,
        difficulty: Optional[int] = None,
        status: Optional[str] = None,
    ) -> List[BenchmarkTaskSchema]:
        """Filter tasks by various attributes."""
        res = list(self._tasks.values())
        if domain:
            res = [t for t in res if t.domain.lower() == domain.lower()]
        if task_type:
            res = [t for t in res if t.task_type.value.lower() == task_type.lower() or t.task_type == task_type]
        if difficulty is not None:
            res = [t for t in res if t.difficulty.initial == difficulty]
        if status:
            res = [t for t in res if t.status.value.lower() == status.lower() or t.status == status]
        return res

    def to_ticket(self, task: BenchmarkTaskSchema) -> Ticket:
        """Convert BenchmarkTaskSchema to MA-SET Ticket for backward compatibility."""
        type_map = {
            TaskType.BUG_FIX: TicketType.BUG,
            TaskType.FEATURE_IMPL: TicketType.FEATURE,
            TaskType.REFACTORING: TicketType.TASK,
            TaskType.TESTING: TicketType.TASK,
            TaskType.SECURITY: TicketType.TASK,
            TaskType.DEVOPS: TicketType.TASK,
            TaskType.ADVERSARIAL: TicketType.TASK,
        }
        ticket_type = type_map.get(task.task_type, TicketType.TASK)
        priority = TicketPriority.HIGH if task.difficulty.initial >= 4 else TicketPriority.MEDIUM

        acceptance = list(task.requirements)
        if task.constraints.protected_files:
            for p in task.constraints.protected_files:
                acceptance.append(f"Protected path {p} is unchanged")

        return Ticket(
            id=task.id,
            title=task.title,
            description=task.prompt,
            type=ticket_type,
            priority=priority,
            acceptance_criteria=acceptance,
            labels=[task.domain, task.subcategory, task.task_type.value],
        )
