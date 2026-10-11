"""ma_set.benchmark package — Benchmark task set, environment, adapters, and evaluation runner"""

from ma_set.benchmark.tasks import BENCHMARK_TASKS
from ma_set.benchmark.runner import (
    BenchmarkRunner,
    BenchmarkReport,
    TaskMetric,
    AgentComparisonSummary,
    ComparisonReport,
)
from ma_set.benchmark.registry import TaskRegistry
from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment
from ma_set.benchmark.adapters.base import AgentAdapter, AgentRunResult
from ma_set.benchmark.adapters.stub import StubAgentAdapter
from ma_set.benchmark.adapters.single_agent import SingleAgentAdapter
from ma_set.benchmark.adapters.maset_team import MasetTeamAdapter

__all__ = [
    "BENCHMARK_TASKS",
    "BenchmarkRunner",
    "BenchmarkReport",
    "TaskMetric",
    "AgentComparisonSummary",
    "ComparisonReport",
    "TaskRegistry",
    "IsolatedEnvironment",
    "AgentAdapter",
    "AgentRunResult",
    "StubAgentAdapter",
    "SingleAgentAdapter",
    "MasetTeamAdapter",
]

