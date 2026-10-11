"""
Agent Adapters Module
=====================
Exposes standard adapters for evaluating single AI agents and multi-agent teams.
"""

from ma_set.benchmark.adapters.base import AgentAdapter, AgentRunResult
from ma_set.benchmark.adapters.maset_team import MasetTeamAdapter
from ma_set.benchmark.adapters.single_agent import SingleAgentAdapter
from ma_set.benchmark.adapters.stub import StubAgentAdapter
from ma_set.benchmark.adapters.model_agents import (
    ClaudeAgentAdapter,
    GptAgentAdapter,
    GeminiAgentAdapter,
)

__all__ = [
    "AgentAdapter",
    "AgentRunResult",
    "MasetTeamAdapter",
    "SingleAgentAdapter",
    "StubAgentAdapter",
    "ClaudeAgentAdapter",
    "GptAgentAdapter",
    "GeminiAgentAdapter",
]

