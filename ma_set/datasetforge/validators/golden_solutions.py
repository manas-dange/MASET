"""MA-SET Lab: Golden Solution Verifier.

Verifies that a benchmark task's reference (golden) patch cleanly applies
and passes 100% of functional and regression tests in an isolated workspace.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ma_set.evaluation.functional import FunctionalEvaluator

from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment
from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema


@dataclass
class GoldenVerificationResult:
    task_id: str
    verified: bool
    applied_cleanly: bool
    tests_passed: bool
    summary: str
    failures: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "verified": self.verified,
            "applied_cleanly": self.applied_cleanly,
            "tests_passed": self.tests_passed,
            "summary": self.summary,
            "failures": self.failures,
        }


class GoldenSolutionVerifier:
    """Verifies that golden patches cleanly solve the task."""

    def __init__(self, functional_evaluator: Optional[FunctionalEvaluator] = None):
        if functional_evaluator is None:
            from ma_set.evaluation.functional import FunctionalEvaluator as _FuncEval
            self.functional_eval = _FuncEval()
        else:
            self.functional_eval = functional_evaluator

    def verify_in_env(
        self,
        task: BenchmarkTaskSchema,
        env: IsolatedEnvironment,
    ) -> GoldenVerificationResult:
        if not task.golden_patch:
            return GoldenVerificationResult(
                task_id=task.id,
                verified=False,
                applied_cleanly=False,
                tests_passed=False,
                summary="No golden patch provided for task.",
                failures=["Missing golden_patch in task definition."],
            )

        # Write patch file into workspace and apply with git apply
        patch_file = env.workspace_path / ".golden.patch"
        patch_file.write_text(task.golden_patch, encoding="utf-8")

        apply_res = env.execute_command(f"git apply --whitespace=nowarn {patch_file.name}")
        if apply_res.exit_code != 0:
            return GoldenVerificationResult(
                task_id=task.id,
                verified=False,
                applied_cleanly=False,
                tests_passed=False,
                summary=f"Git apply failed: {apply_res.stderr or apply_res.stdout}",
                failures=[f"Git apply error: {apply_res.stderr}"],
            )

        # Run functional evaluation
        test_cmds = task.evaluation.functional_tests or None
        eval_res = self.functional_eval.evaluate(
            workspace_dir=env.workspace_path,
            test_commands=test_cmds,
        )

        verified = eval_res.success
        return GoldenVerificationResult(
            task_id=task.id,
            verified=verified,
            applied_cleanly=True,
            tests_passed=eval_res.success,
            summary="Golden solution verified successfully." if verified else f"{eval_res.failed_count} tests failed.",
            failures=[f"{f.test_name}: {f.message}" for f in eval_res.failures],
        )

    def verify(
        self,
        task: BenchmarkTaskSchema,
        base_source_dir: Path,
    ) -> GoldenVerificationResult:
        with tempfile.TemporaryDirectory(prefix=f"maset_golden_{task.id}_") as tmp:
            env = IsolatedEnvironment(
                task_id=task.id,
                source_dir=base_source_dir,
                workspace_path=Path(tmp) / "workspace",
            )
            try:
                env.setup()
                return self.verify_in_env(task, env)
            finally:
                env.teardown()
