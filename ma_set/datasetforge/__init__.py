"""MA-SET Lab: DatasetForge Task Engineering Platform.

Manages task authoring, schema validation, golden/negative solutions,
duplicate detection, peer review, and difficulty calibration.
"""

from ma_set.datasetforge.schemas.task import (
    BenchmarkTaskSchema,
    TaskType,
    TaskStatus,
    DifficultyConfig,
    ConstraintsConfig,
    EvaluationConfig,
    CalibrationConfig,
    MetadataConfig,
    NegativePatch,
)
from ma_set.datasetforge.validators.task_validator import TaskValidator, TaskValidationResult
from ma_set.datasetforge.validators.golden_solutions import GoldenSolutionVerifier, GoldenVerificationResult
from ma_set.datasetforge.validators.negative_solutions import NegativeSolutionsVerifier, NegativeSolutionResult
from ma_set.datasetforge.validators.duplicate_detector import DuplicateDetector, DuplicateMatch
from ma_set.datasetforge.calibration.calibrator import DifficultyCalibrator, CalibrationRecord
from ma_set.datasetforge.reviewers.review_workflow import ReviewWorkflow, ReviewDecision, ReviewWorkflowState

__all__ = [
    "BenchmarkTaskSchema",
    "TaskType",
    "TaskStatus",
    "DifficultyConfig",
    "ConstraintsConfig",
    "EvaluationConfig",
    "CalibrationConfig",
    "MetadataConfig",
    "NegativePatch",
    "TaskValidator",
    "TaskValidationResult",
    "GoldenSolutionVerifier",
    "GoldenVerificationResult",
    "NegativeSolutionsVerifier",
    "NegativeSolutionResult",
    "DuplicateDetector",
    "DuplicateMatch",
    "DifficultyCalibrator",
    "CalibrationRecord",
    "ReviewWorkflow",
    "ReviewDecision",
    "ReviewWorkflowState",
]
