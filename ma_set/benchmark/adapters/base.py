"""
Agent Adapter Interface
=======================
Standard interface allowing any AI coding agent or multi-agent team to be evaluated
identically against TerminalBench tasks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment
from ma_set.tools.ticket_intake import Ticket


@dataclass
class AgentRunResult:
    """Standardized result returned by an AgentAdapter after executing a benchmark task."""

    agent_name: str
    agent_version: str
    success: bool
    output: str
    diff: str = ""
    files_modified: List[str] = field(default_factory=list)
    commands_executed: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    escalation_reason: Optional[str] = None


    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "success": self.success,
            "output": self.output[:1000],
            "diff_chars": len(self.diff),
            "files_modified": self.files_modified,
            "commands_executed": self.commands_executed,
            "llm_calls": self.llm_calls,
            "cost_usd": round(self.cost_usd, 4),
            "duration_s": round(self.duration_s, 3),
            "escalation_reason": self.escalation_reason,
        }


class AgentAdapter(ABC):
    """Abstract base class for all AI agent evaluators."""

    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version

    @abstractmethod
    def run(
        self,
        task: Ticket | Any,
        environment: IsolatedEnvironment,
        config: Optional[Dict[str, Any]] = None,
    ) -> AgentRunResult:
        """
        Execute the agent on *task* inside *environment*.
        Returns a structured AgentRunResult.
        """
        pass
