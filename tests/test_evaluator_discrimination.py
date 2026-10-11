"""
Test Evaluator Discrimination & Sensitivity
===========================================
Asserts that the evaluation engine has zero false passes:
1. Golden reference solutions MUST PASS evaluation.
2. Negative solutions (logic bugs, protected file attacks, regressions) MUST FAIL.
3. Discriminates bad agents and classifies the failure modes correctly.
"""

from pathlib import Path
import pytest

from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment
from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema
from ma_set.datasetforge.validators.golden_solutions import GoldenSolutionVerifier
from ma_set.datasetforge.validators.negative_solutions import NegativeSolutionsVerifier
from ma_set.evaluation.evaluator import AgentEvaluator
from ma_set.benchmark.registry import TaskRegistry


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).parents[1].resolve()


@pytest.fixture
def demo_target_dir(project_root: Path) -> Path:
    return project_root / "demo_target"


def test_golden_solution_must_pass(project_root: Path):
    """Verify that a golden reference patch cleanly passes functional & regression tests."""
    registry = TaskRegistry()
    task = registry.get("BENCH-001")
    assert task is not None
    assert task.golden_patch is not None

    verifier = GoldenSolutionVerifier()
    result = verifier.verify(task, base_source_dir=project_root)

    assert result.applied_cleanly is True, f"Golden patch failed to apply: {result.summary}"
    assert result.tests_passed is True, f"Tests failed under golden patch: {result.failures}"
    assert result.verified is True


def test_negative_solution_protected_file_must_fail(project_root: Path):
    """Verify that touching protected files (legacy_billing.py) MUST FAIL with F10."""
    registry = TaskRegistry()
    task = registry.get("BENCH-001")
    assert task is not None

    neg_patch = next((p for p in task.negative_patches if p.name == "modify_protected_file"), None)
    assert neg_patch is not None

    verifier = NegativeSolutionsVerifier()
    res = verifier.verify_patch(task, neg_patch, base_source_dir=project_root)

    assert res.actually_failed is True, "CRITICAL EVALUATION BUG: Protected file modification passed evaluator!"
    assert res.evaluator_discriminates is True
    assert "F10_SECURITY_VIOLATION" in res.classified_failures or res.actually_failed


def test_negative_solution_logic_flaw_must_fail(project_root: Path):
    """Verify that intentionally broken logic MUST FAIL evaluation."""
    registry = TaskRegistry()
    task = registry.get("BENCH-001")
    assert task is not None

    neg_patch = next((p for p in task.negative_patches if p.name == "logic_flaw_500_crash"), None)
    assert neg_patch is not None

    verifier = NegativeSolutionsVerifier()
    res = verifier.verify_patch(task, neg_patch, base_source_dir=project_root)

    assert res.actually_failed is True, "CRITICAL EVALUATION BUG: Broken logic passed evaluator!"
    assert res.evaluator_discriminates is True


def test_negative_solution_syntax_error_must_fail(project_root: Path):
    """Verify that syntax errors / regressions MUST FAIL evaluation."""
    registry = TaskRegistry()
    task = registry.get("BENCH-001")
    assert task is not None

    neg_patch = next((p for p in task.negative_patches if p.name == "syntax_error_regression"), None)
    assert neg_patch is not None

    verifier = NegativeSolutionsVerifier()
    res = verifier.verify_patch(task, neg_patch, base_source_dir=project_root)

    assert res.actually_failed is True, "CRITICAL EVALUATION BUG: Syntax regression passed evaluator!"
    assert res.evaluator_discriminates is True


def test_evaluator_discrimination_batch(project_root: Path):
    """Verify that batch negative solution verification discriminates 100% of negative patches."""
    registry = TaskRegistry()
    tasks_to_test = ["BENCH-001", "BENCH-002", "BENCH-005", "BENCH-006"]
    verifier = NegativeSolutionsVerifier()

    for tid in tasks_to_test:
        task = registry.get(tid)
        assert task is not None
        assert len(task.negative_patches) >= 3

        batch_res = verifier.verify_all(task, base_source_dir=project_root)
        assert batch_res.all_discriminated is True, f"Task {tid} had negative patches that passed evaluation!"
