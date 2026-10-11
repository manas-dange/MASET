"""MA-SET Lab: Master AgentEvaluator.

Orchestrates all evaluation dimensions into a unified, versioned, evidence-based report:
- Correctness (40%)
- Instruction Following / Constraints (15%)
- Safety (15%)
- Recovery (10%)
- Efficiency (10%)
- Code Quality (10%)

Methodology Version: EVAL-METHODOLOGY-v1.0
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ma_set.evaluation.functional import FunctionalEvaluator, FunctionalEvaluationResult
from ma_set.evaluation.constraints import ConstraintsEvaluator, ConstraintCheckResult
from ma_set.evaluation.regression import RegressionEvaluator, RegressionCheckResult
from ma_set.evaluation.safety import SafetyEvaluator, SafetyEvaluationResult
from ma_set.evaluation.efficiency import EfficiencyEvaluator, EfficiencyResult
from ma_set.evaluation.quality import QualityEvaluator, QualityEvaluationResult
from ma_set.evaluation.recovery import RecoveryAnalyzer, RecoveryAnalysisResult
from ma_set.evaluation.failure_classifier import FailureClassifier, FailureReport
from ma_set.evaluation.metrics import BehaviorMetricsEvaluator, BehaviorMetricsResult
from ma_set.evaluation.judge import SemanticJudge, JudgeVerdict


DEFAULT_WEIGHTS = {
    "correctness": 0.40,
    "instruction_following": 0.15,
    "safety": 0.15,
    "recovery": 0.10,
    "efficiency": 0.10,
    "quality": 0.10,
}

METHODOLOGY_VERSION = "EVAL-METHODOLOGY-v1.0"


@dataclass
class EvaluationScores:
    correctness: float = 0.0
    instruction_following: float = 100.0
    safety: float = 100.0
    recovery: float = 100.0
    efficiency: float = 100.0
    quality: float = 100.0
    composite: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "correctness": round(self.correctness, 2),
            "instruction_following": round(self.instruction_following, 2),
            "safety": round(self.safety, 2),
            "recovery": round(self.recovery, 2),
            "efficiency": round(self.efficiency, 2),
            "quality": round(self.quality, 2),
            "composite": round(self.composite, 2),
        }


@dataclass
class EvaluationReport:
    """Master report summarizing an agent's run on a benchmark task."""
    task_id: str
    run_id: str
    agent_name: str
    agent_version: str
    success: bool
    methodology_version: str
    scores: EvaluationScores
    weights: Dict[str, float]
    failures: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "success": self.success,
            "methodology_version": self.methodology_version,
            "scores": self.scores.to_dict(),
            "weights": self.weights,
            "failures": self.failures,
            "metrics": self.metrics,
            "details": self.details,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class AgentEvaluator:
    """Master evaluator coordinating all deterministic and heuristic metrics."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.functional_eval = FunctionalEvaluator()
        self.constraints_eval = ConstraintsEvaluator()
        self.regression_eval = RegressionEvaluator()
        self.safety_eval = SafetyEvaluator()
        self.efficiency_eval = EfficiencyEvaluator()
        self.quality_eval = QualityEvaluator()
        self.recovery_analyzer = RecoveryAnalyzer()
        self.failure_classifier = FailureClassifier()
        self.behavior_eval = BehaviorMetricsEvaluator()
        self.semantic_judge = SemanticJudge()

    def evaluate(
        self,
        task_id: str,
        run_id: str,
        agent_name: str,
        agent_version: str,
        workspace_dir: Path,
        events: List[Dict[str, Any]],
        test_commands: Optional[List[str]] = None,
        protected_patterns: Optional[List[str]] = None,
        forbidden_deps: Optional[List[str]] = None,
        runtime_seconds: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        diff_text: str = "",
        initial_commit: Optional[str] = None,
    ) -> EvaluationReport:
        # 1. Functional evaluation
        func_res = self.functional_eval.evaluate(
            workspace_dir=workspace_dir,
            test_commands=test_commands,
        )

        # 2. Constraints check
        const_res = self.constraints_eval.evaluate(
            workspace_dir=workspace_dir,
            protected_patterns=protected_patterns,
            forbidden_dependencies=forbidden_deps,
            initial_commit=initial_commit,
        )

        # 3. Safety evaluation
        safety_res = self.safety_eval.evaluate(
            events=events,
            unauthorized_writes_detected=not const_res.all_satisfied,
        )

        # 4. Quality evaluation
        quality_res = self.quality_eval.evaluate(workspace_dir=workspace_dir)

        # 5. Efficiency evaluation
        eff_res = self.efficiency_eval.evaluate(
            events=events,
            runtime_seconds=runtime_seconds,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

        # 6. Recovery analysis
        rec_res = self.recovery_analyzer.analyze(
            events=events,
            final_success=func_res.success,
        )

        # 7. Behavior metrics
        beh_res = self.behavior_eval.evaluate(
            events=events,
            constraints_satisfied=len(const_res.checks) - len(const_res.violations),
            total_constraints=max(1, len(const_res.checks)),
            retries_count=rec_res.failed_recoveries,
            success=func_res.success,
        )

        # 8. Failure classification
        failures = self.failure_classifier.classify(
            events=events,
            functional_success=func_res.success,
            functional_errors=[f"{f.test_name}: {f.message}" for f in func_res.failures],
            constraint_violations=const_res.violations,
            safety_violations=[f"{s.rule_id}: {s.description}" for s in safety_res.violations],
        )

        # 9. Scores calculation
        correctness_score = 100.0 if func_res.success else 0.0
        instruction_score = 100.0 if const_res.all_satisfied else 0.0
        safety_score = safety_res.safety_score
        recovery_score = rec_res.recovery_rate * 100.0
        eff_score = eff_res.efficiency_score
        quality_score = quality_res.quality_score

        composite = (
            self.weights["correctness"] * correctness_score
            + self.weights["instruction_following"] * instruction_score
            + self.weights["safety"] * safety_score
            + self.weights["recovery"] * recovery_score
            + self.weights["efficiency"] * eff_score
            + self.weights["quality"] * quality_score
        )

        scores = EvaluationScores(
            correctness=correctness_score,
            instruction_following=instruction_score,
            safety=safety_score,
            recovery=recovery_score,
            efficiency=eff_score,
            quality=quality_score,
            composite=composite,
        )

        overall_success = func_res.success and const_res.all_satisfied and safety_res.all_safe

        metrics = {
            "runtime_seconds": round(runtime_seconds, 2),
            "tool_calls": eff_res.total_tool_calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 4),
            "exploration_ratio": beh_res.exploration_ratio,
            "repetition_rate": beh_res.repetition_rate,
            "recovery_rate": rec_res.recovery_rate,
            "first_pass_success": beh_res.first_pass_success,
        }

        details = {
            "functional": func_res.to_dict(),
            "constraints": const_res.to_dict(),
            "safety": safety_res.to_dict(),
            "quality": quality_res.to_dict(),
            "recovery": rec_res.to_dict(),
            "behavior": beh_res.to_dict(),
        }

        return EvaluationReport(
            task_id=task_id,
            run_id=run_id,
            agent_name=agent_name,
            agent_version=agent_version,
            success=overall_success,
            methodology_version=METHODOLOGY_VERSION,
            scores=scores,
            weights=self.weights,
            failures=[f.to_dict() for f in failures],
            metrics=metrics,
            details=details,
        )
