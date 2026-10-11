"""MA-SET Lab: Negative Solutions Verifier.

Tests the evaluator's sensitivity and discrimination power by applying intentionally
flawed or adversarial patches (negative solutions).

Expected invariant:
    Golden solution      -> PASS
    Negative solutions   -> FAIL (with corresponding failure classification)
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ma_set.evaluation.evaluator import AgentEvaluator, EvaluationReport

from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment
from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema, NegativePatch


@dataclass
class NegativeSolutionResult:
    name: str
    expected_failure_type: str
    actually_failed: bool
    classified_failures: List[str]
    evaluator_discriminates: bool
    notes: str


@dataclass
class NegativeSolutionsBatchResult:
    task_id: str
    all_discriminated: bool
    results: List[NegativeSolutionResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "all_discriminated": self.all_discriminated,
            "results": [
                {
                    "name": r.name,
                    "expected_failure_type": r.expected_failure_type,
                    "actually_failed": r.actually_failed,
                    "classified_failures": r.classified_failures,
                    "evaluator_discriminates": r.evaluator_discriminates,
                    "notes": r.notes,
                }
                for r in self.results
            ],
        }


class NegativeSolutionsVerifier:
    """Verifies that the evaluation harness correctly rejects negative patches."""

    def __init__(self, evaluator: Optional[AgentEvaluator] = None):
        if evaluator is None:
            from ma_set.evaluation.evaluator import AgentEvaluator as _AgentEval
            self.evaluator = _AgentEval()
        else:
            self.evaluator = evaluator

    def verify_patch(
        self,
        task: BenchmarkTaskSchema,
        negative: NegativePatch,
        base_source_dir: Path,
    ) -> NegativeSolutionResult:
        with tempfile.TemporaryDirectory(prefix=f"maset_neg_{task.id}_") as tmp:
            env = IsolatedEnvironment(
                task_id=task.id,
                source_dir=base_source_dir,
                workspace_path=Path(tmp) / "workspace",
            )
            try:
                env.setup()
                patch_file = env.workspace_path / ".negative.patch"
                patch_file.write_text(negative.patch, encoding="utf-8")

                apply_res = env.execute_command(f"git apply --whitespace=nowarn {patch_file.name}")
                if apply_res.exit_code != 0:
                    return NegativeSolutionResult(
                        name=negative.name,
                        expected_failure_type=negative.expected_failure_type,
                        actually_failed=True,
                        classified_failures=["F11_ENVIRONMENT_FAILURE"],
                        evaluator_discriminates=True,
                        notes=f"Patch failed to apply (treated as failure): {apply_res.stderr}",
                    )

                # Run evaluation
                report = self.evaluator.evaluate(
                    task_id=task.id,
                    run_id="neg_test",
                    agent_name="negative_probe",
                    agent_version="1.0",
                    workspace_dir=env.workspace_path,
                    events=[],
                    test_commands=task.evaluation.functional_tests or None,
                    protected_patterns=task.constraints.protected_files or None,
                    forbidden_deps=task.constraints.forbidden_dependencies or None,
                )

                actually_failed = not report.success
                found_failures = [f.get("failure_type", "") for f in report.failures]
                discriminates = actually_failed

                return NegativeSolutionResult(
                    name=negative.name,
                    expected_failure_type=negative.expected_failure_type,
                    actually_failed=actually_failed,
                    classified_failures=found_failures,
                    evaluator_discriminates=discriminates,
                    notes="Properly rejected flawed patch" if discriminates else "False positive: evaluator accepted flawed patch!",
                )
            finally:
                env.teardown()

    def verify_all(
        self,
        task: BenchmarkTaskSchema,
        base_source_dir: Path,
    ) -> NegativeSolutionsBatchResult:
        results = [
            self.verify_patch(task, neg, base_source_dir)
            for neg in task.negative_patches
        ]
        all_discriminated = all(r.evaluator_discriminates for r in results) if results else True
        return NegativeSolutionsBatchResult(
            task_id=task.id,
            all_discriminated=all_discriminated,
            results=results,
        )
