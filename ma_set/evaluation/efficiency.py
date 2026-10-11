"""
Efficiency Evaluator (AgentEval)
================================
Measures agent execution efficiency:
  - Tool calls and command volume
  - Runtime duration
  - LLM call count, token usage & estimated cost
  - File inspection vs modification ratio
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from ma_set.benchmark.adapters.base import AgentRunResult
from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment


class EfficiencyEvaluationResult:
    def __init__(
        self,
        command_count: int,
        llm_calls: int,
        duration_s: float,
        cost_usd: float,
        files_inspected_count: int,
        files_modified_count: int,
        efficiency_score: float,
    ):
        self.command_count = command_count
        self.llm_calls = llm_calls
        self.duration_s = duration_s
        self.cost_usd = cost_usd
        self.files_inspected_count = files_inspected_count
        self.files_modified_count = files_modified_count
        self.efficiency_score = efficiency_score

        self.total_tool_calls = command_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "efficiency_score": round(self.efficiency_score, 1),
            "command_count": self.command_count,
            "total_tool_calls": self.total_tool_calls,
            "llm_calls": self.llm_calls,
            "duration_s": round(self.duration_s, 2),
            "cost_usd": round(self.cost_usd, 4),
            "files_inspected": self.files_inspected_count,
            "files_modified": self.files_modified_count,
        }


EfficiencyResult = EfficiencyEvaluationResult


class EfficiencyEvaluator:
    """Evaluates how efficiently an agent completed the task."""

    def __init__(self, target_max_commands: int = 15, target_max_duration: float = 60.0):
        self.target_max_commands = target_max_commands
        self.target_max_duration = target_max_duration

    def evaluate(
        self,
        environment: Any = None,
        agent_result: Optional[AgentRunResult] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        runtime_seconds: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> EfficiencyEvaluationResult:
        if environment is not None and hasattr(environment, "commands_executed"):
            cmd_count = len(environment.commands_executed)
            inspected = len(getattr(environment, "files_inspected", []))
            modified = len(getattr(environment, "files_modified", []))
            duration = agent_result.duration_s if agent_result else (runtime_seconds or 5.0)
            llm_calls = agent_result.llm_calls if agent_result else 2
            cost = agent_result.cost_usd if agent_result else (cost_usd or (llm_calls * 0.0002))
        elif events is not None:
            cmd_count = sum(1 for e in events if e.get("event_type") in ("TOOL_CALL", "SANDBOX_COMMAND", "terminal_command"))
            inspected = sum(1 for e in events if "path" in e.get("payload", {}) or "file" in e.get("payload", {}))
            modified = sum(1 for e in events if e.get("event_type") in ("FILE_WRITE_ALLOWED", "DIFF_PRODUCED"))
            duration = runtime_seconds or 5.0
            llm_calls = sum(1 for e in events if e.get("event_type") == "LLM_REQUEST")
            cost = cost_usd or ((tokens_in + tokens_out) * 0.000002)
        else:
            cmd_count = 0
            inspected = 0
            modified = 0
            duration = runtime_seconds
            llm_calls = 0
            cost = cost_usd

        score = 100.0
        if cmd_count > self.target_max_commands:
            score -= (cmd_count - self.target_max_commands) * 4.0
        if duration > self.target_max_duration:
            score -= ((duration - self.target_max_duration) / 10.0) * 5.0
        if llm_calls > 15:
            score -= (llm_calls - 15) * 5.0

        score = max(10.0, min(100.0, score))

        return EfficiencyEvaluationResult(
            command_count=cmd_count,
            llm_calls=llm_calls,
            duration_s=duration,
            cost_usd=cost,
            files_inspected_count=inspected,
            files_modified_count=modified,
            efficiency_score=score,
        )

