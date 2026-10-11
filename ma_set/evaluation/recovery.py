"""MA-SET Lab: Recovery Analysis Subsystem.

Tracks and quantifies how software engineering agents respond when encountering errors,
test failures, or exception tracebacks during execution:
- Notices failure & fixes -> Successful Recovery
- Notices failure & wrong fix -> Repeated Failure / Failure Escalation
- Ignores failure & submits -> Ignored Failure

Metric:
    Recovery Rate = Successful Recoveries / Recoverable Failures
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RecoveryEpisode:
    """A single episode where an agent encountered a failure and attempted recovery."""
    episode_id: str
    trigger_event_type: str
    trigger_message: str
    start_step: int
    resolved_step: Optional[int] = None
    attempts: int = 0
    successful: bool = False
    repeated_failures: int = 0
    escalated: bool = False
    actions_taken: List[str] = field(default_factory=list)


@dataclass
class RecoveryAnalysisResult:
    """Summary metrics of an agent's error recovery capabilities."""
    total_recoverable_failures: int
    successful_recoveries: int
    failed_recoveries: int
    ignored_failures: int
    recovery_rate: float  # successful_recoveries / total_recoverable_failures (or 1.0 if 0 failures)
    average_attempts_to_recover: float
    repeated_failure_count: int
    escalation_count: int
    episodes: List[RecoveryEpisode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_recoverable_failures": self.total_recoverable_failures,
            "successful_recoveries": self.successful_recoveries,
            "failed_recoveries": self.failed_recoveries,
            "ignored_failures": self.ignored_failures,
            "recovery_rate": round(self.recovery_rate, 4),
            "average_attempts_to_recover": round(self.average_attempts_to_recover, 2),
            "repeated_failure_count": self.repeated_failure_count,
            "escalation_count": self.escalation_count,
            "episodes": [
                {
                    "episode_id": ep.episode_id,
                    "trigger": ep.trigger_message,
                    "attempts": ep.attempts,
                    "successful": ep.successful,
                    "repeated_failures": ep.repeated_failures,
                    "escalated": ep.escalated,
                }
                for ep in self.episodes
            ],
        }


class RecoveryAnalyzer:
    """Analyzes agent event trajectories for failure recovery dynamics."""

    def analyze(
        self,
        events: List[Dict[str, Any]],
        final_success: bool = False,
    ) -> RecoveryAnalysisResult:
        """Parse structured trajectory events to detect and evaluate recovery episodes."""
        episodes: List[RecoveryEpisode] = []
        current_episode: Optional[RecoveryEpisode] = None
        episode_counter = 0

        for idx, event in enumerate(events):
            event_type = str(event.get("event_type", "")).lower()
            payload = event.get("payload", {})

            # Check if this event represents a test/command failure
            is_failure = False
            fail_msg = ""

            if event_type == "test_results" and not payload.get("passed", True):
                is_failure = True
                fail_msg = f"Test failure: {payload.get('summary', 'tests failed')}"
            elif event_type in ("sandbox_result", "tool_result", "command_result"):
                exit_code = payload.get("exit_code") or payload.get("status_code", 0)
                if exit_code not in (0, None):
                    is_failure = True
                    fail_msg = f"Command exit {exit_code}: {str(payload.get('stderr') or payload.get('output', ''))[:100]}"
            elif event_type in ("failure_detected", "failure_classified"):
                is_failure = True
                fail_msg = payload.get("description", payload.get("error", "Failure detected"))

            # Check if this event represents a test pass or successful resolution
            is_success_resolution = False
            if event_type == "test_results" and payload.get("passed", False):
                is_success_resolution = True
            elif event_type in ("recovery_succeeded",):
                is_success_resolution = True

            # State machine for episodes
            if is_failure:
                if current_episode is None:
                    episode_counter += 1
                    current_episode = RecoveryEpisode(
                        episode_id=f"REC-{episode_counter:03d}",
                        trigger_event_type=event_type,
                        trigger_message=fail_msg,
                        start_step=idx,
                        attempts=0,
                    )
                    episodes.append(current_episode)
                else:
                    # Repeated failure within an existing episode
                    current_episode.attempts += 1
                    current_episode.repeated_failures += 1
                    if current_episode.repeated_failures >= 2:
                        current_episode.escalated = True

            elif is_success_resolution:
                if current_episode is not None:
                    current_episode.successful = True
                    current_episode.resolved_step = idx
                    current_episode = None

            elif current_episode is not None:
                # Intermediate action during recovery
                if event_type in ("tool_call", "file_write_allowed", "sandbox_command", "terminal_command", "recovery_started"):
                    current_episode.attempts += 1
                    tool_desc = payload.get("tool") or payload.get("command") or event_type
                    current_episode.actions_taken.append(str(tool_desc))

        # If run ended and episode was never marked successful, check final_success
        if current_episode is not None:
            if final_success:
                current_episode.successful = True
            else:
                current_episode.successful = False

        total_failures = len(episodes)
        if total_failures == 0:
            return RecoveryAnalysisResult(
                total_recoverable_failures=0,
                successful_recoveries=0,
                failed_recoveries=0,
                ignored_failures=0,
                recovery_rate=1.0,
                average_attempts_to_recover=0.0,
                repeated_failure_count=0,
                escalation_count=0,
                episodes=[],
            )

        successful = sum(1 for ep in episodes if ep.successful)
        failed = sum(1 for ep in episodes if not ep.successful)
        ignored = sum(1 for ep in episodes if not ep.successful and ep.attempts <= 1)
        repeated = sum(ep.repeated_failures for ep in episodes)
        escalations = sum(1 for ep in episodes if ep.escalated)
        total_attempts = sum(ep.attempts for ep in episodes)

        recovery_rate = successful / total_failures
        avg_attempts = total_attempts / total_failures if total_failures > 0 else 0.0

        return RecoveryAnalysisResult(
            total_recoverable_failures=total_failures,
            successful_recoveries=successful,
            failed_recoveries=failed,
            ignored_failures=ignored,
            recovery_rate=recovery_rate,
            average_attempts_to_recover=avg_attempts,
            repeated_failure_count=repeated,
            escalation_count=escalations,
            episodes=episodes,
        )
