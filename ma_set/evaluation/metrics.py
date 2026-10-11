"""MA-SET Lab: Agent Behavior Metrics Subsystem.

Calculates behavioral indices:
- Exploration Ratio: exploration commands / total commands
- Repetition Rate: repeated identical actions / total actions
- Constraint Compliance: constraints satisfied / total constraints
- First-Pass Success: whether task solved without any retry/recovery loops
- Operational aggregates: tool calls, runtime, tokens, cost, files inspected, files changed, test runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


EXPLORATION_KEYWORDS = {
    "ls", "dir", "find", "grep", "cat", "head", "tail", "less",
    "tree", "read", "view", "search", "locate", "stat", "inspect"
}


@dataclass
class BehaviorMetricsResult:
    """Quantitative evaluation of an agent's execution behavior."""
    total_actions: int = 0
    exploration_commands: int = 0
    exploration_ratio: float = 0.0
    repetition_rate: float = 0.0
    repeated_actions_count: int = 0
    constraint_compliance_rate: float = 1.0
    first_pass_success: bool = True
    files_inspected: List[str] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    test_runs_count: int = 0
    failed_test_runs_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_actions": self.total_actions,
            "exploration_commands": self.exploration_commands,
            "exploration_ratio": round(self.exploration_ratio, 4),
            "repetition_rate": round(self.repetition_rate, 4),
            "repeated_actions_count": self.repeated_actions_count,
            "constraint_compliance_rate": round(self.constraint_compliance_rate, 4),
            "first_pass_success": self.first_pass_success,
            "files_inspected_count": len(self.files_inspected),
            "files_changed_count": len(self.files_changed),
            "test_runs_count": self.test_runs_count,
            "failed_test_runs_count": self.failed_test_runs_count,
        }


class BehaviorMetricsEvaluator:
    """Computes behavioral patterns and indices from execution trajectories."""

    def evaluate(
        self,
        events: List[Dict[str, Any]],
        constraints_satisfied: int = 1,
        total_constraints: int = 1,
        retries_count: int = 0,
        success: bool = True,
    ) -> BehaviorMetricsResult:
        total_actions = 0
        exploration_count = 0
        actions_seen: Set[str] = set()
        repeated_count = 0
        inspected_files: Set[str] = set()
        changed_files: Set[str] = set()
        test_runs = 0
        failed_test_runs = 0

        for event in events:
            event_type = event.get("event_type", "")
            payload = event.get("payload", {})

            if event_type in ("TOOL_CALL", "SANDBOX_COMMAND"):
                total_actions += 1
                cmd = str(payload.get("command") or payload.get("tool") or "").strip()
                action_sig = f"{event_type}:{cmd}"

                if action_sig in actions_seen:
                    repeated_count += 1
                else:
                    actions_seen.add(action_sig)

                # Check if exploration
                cmd_first_word = cmd.split()[0].lower() if cmd else ""
                if cmd_first_word in EXPLORATION_KEYWORDS or any(kw in cmd.lower() for kw in ("grep ", "cat ", "find ")):
                    exploration_count += 1

                # Check inspect target
                target = payload.get("path") or payload.get("file")
                if target:
                    inspected_files.add(str(target))

            elif event_type in ("FILE_WRITE_ALLOWED", "DIFF_PRODUCED"):
                total_actions += 1
                target = payload.get("path") or payload.get("file")
                if target:
                    changed_files.add(str(target))

            elif event_type == "TEST_RESULTS":
                test_runs += 1
                if not payload.get("passed", True):
                    failed_test_runs += 1

        exp_ratio = exploration_count / total_actions if total_actions > 0 else 0.0
        rep_rate = repeated_count / total_actions if total_actions > 0 else 0.0
        compliance_rate = (
            constraints_satisfied / total_constraints if total_constraints > 0 else 1.0
        )
        first_pass = success and (retries_count == 0) and (failed_test_runs == 0)

        return BehaviorMetricsResult(
            total_actions=total_actions,
            exploration_commands=exploration_count,
            exploration_ratio=exp_ratio,
            repetition_rate=rep_rate,
            repeated_actions_count=repeated_count,
            constraint_compliance_rate=compliance_rate,
            first_pass_success=first_pass,
            files_inspected=sorted(list(inspected_files)),
            files_changed=sorted(list(changed_files)),
            test_runs_count=test_runs,
            failed_test_runs_count=failed_test_runs,
        )
