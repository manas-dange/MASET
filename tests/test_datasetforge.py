"""Tests for MA-SET Lab 2.0: DatasetForge Subsystem."""

import pytest
from pathlib import Path

from ma_set.benchmark.registry import TaskRegistry
from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema, TaskType, DifficultyConfig
from ma_set.datasetforge.validators.task_validator import TaskValidator
from ma_set.datasetforge.validators.duplicate_detector import DuplicateDetector
from ma_set.datasetforge.calibration.calibrator import DifficultyCalibrator


def test_task_validator_accepts_valid_task():
    validator = TaskValidator()
    task_dict = {
        "id": "BENCH-001",
        "title": "Validate missing email on signup",
        "domain": "backend",
        "prompt": "Reject missing email on /signup with HTTP 400 Bad Request.",
        "requirements": ["Returns HTTP 400 on missing email"],
        "difficulty": {"initial": 2},
        "task_type": "bug_fix",
    }
    res = validator.validate_dict(task_dict)
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_task_validator_catches_contamination():
    validator = TaskValidator()
    task_dict = {
        "id": "BENCH-001",
        "title": "Leaked solution task",
        "domain": "backend",
        "prompt": "diff --git a/app.py b/app.py Here is the answer for signup.",
        "requirements": ["Do something"],
        "difficulty": {"initial": 2},
        "task_type": "bug_fix",
    }
    res = validator.validate_dict(task_dict)
    assert res.is_valid is False
    assert any("leakage" in e.lower() for e in res.errors)


def test_duplicate_detector():
    detector = DuplicateDetector()
    task1 = BenchmarkTaskSchema(
        id="BENCH-001",
        title="Fix email validation",
        prompt="Ensure email is required during registration.",
        requirements=["require email"],
        difficulty=DifficultyConfig(initial=2),
        task_type=TaskType.BUG_FIX,
    )
    task2 = BenchmarkTaskSchema(
        id="BENCH-002",
        title="Fix email validation duplicate",
        prompt="Ensure email is required during registration.",
        requirements=["require email"],
        difficulty=DifficultyConfig(initial=2),
        task_type=TaskType.BUG_FIX,
    )
    matches = detector.find_duplicates([task1, task2])
    assert len(matches) >= 1
    assert matches[0].match_type == "EXACT"


def test_task_registry_loads_v1_dataset():
    registry = TaskRegistry()
    tasks = registry.list_all()
    assert len(tasks) >= 30
    assert registry.get("BENCH-001") is not None
    assert registry.get("BENCH-006").task_type == TaskType.ADVERSARIAL


def test_difficulty_calibrator():
    calibrator = DifficultyCalibrator()
    task = BenchmarkTaskSchema(
        id="BENCH-001",
        title="Test calibration task",
        prompt="A standard benchmark task for calibration testing.",
        requirements=["Requirement A"],
        difficulty=DifficultyConfig(initial=3),
        task_type=TaskType.BUG_FIX,
    )
    record = calibrator.calibrate(task, results=[True, True, True])
    assert record.observed_pass_rate == 1.0
    assert record.recommended_difficulty <= 1.5
