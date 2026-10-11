"""MA-SET Lab: Versioned Benchmark Task Schema.

Defines the strongly typed, Pydantic v2 specification for benchmark tasks
in DatasetForge and TerminalBench.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
import pydantic


class TaskType(str, Enum):
    BUG_FIX         = "bug_fix"
    FEATURE_IMPL    = "feature_impl"
    REFACTORING     = "refactoring"
    TESTING         = "testing"
    SECURITY        = "security"
    DEVOPS          = "devops"
    ADVERSARIAL     = "adversarial"


class TaskStatus(str, Enum):
    DRAFT               = "draft"
    VALIDATION_FAILED   = "validation_failed"
    UNDER_REVIEW        = "under_review"
    ACCEPTED            = "accepted"
    CALIBRATING         = "calibrating"
    REJECTED            = "rejected"
    DEPRECATED          = "deprecated"


class DifficultyConfig(pydantic.BaseModel):
    initial: int = pydantic.Field(ge=1, le=5, description="Initial human rating: 1=trivial to 5=expert")
    calibrated: Optional[float] = pydantic.Field(default=None, ge=1.0, le=5.0, description="Empirically calibrated difficulty")


class ConstraintsConfig(pydantic.BaseModel):
    protected_files: List[str] = pydantic.Field(default_factory=list, description="Glob patterns or paths that must remain untouched")
    forbidden_dependencies: List[str] = pydantic.Field(default_factory=list, description="Packages that may not be added")
    forbidden_commands: List[str] = pydantic.Field(default_factory=list, description="Terminal commands prohibited during execution")


class EvaluationConfig(pydantic.BaseModel):
    functional_tests: List[str] = pydantic.Field(default_factory=list, description="Pytest command args or test ids")
    constraints: List[str] = pydantic.Field(default_factory=list, description="Constraint checks to enforce")
    regression: bool = pydantic.Field(default=True, description="Whether to execute regression suite")
    quality: bool = pydantic.Field(default=True, description="Whether to run lint / AST quality check")


class CalibrationConfig(pydantic.BaseModel):
    target_pass_rate: float = pydantic.Field(default=0.50, ge=0.0, le=1.0)
    runs: int = pydantic.Field(default=0, ge=0)
    observed_pass_rate: Optional[float] = pydantic.Field(default=None, ge=0.0, le=1.0)
    status: str = pydantic.Field(default="pending")


class MetadataConfig(pydantic.BaseModel):
    author: str = pydantic.Field(default="internal")
    source: str = pydantic.Field(default="original")
    created_at: str = pydantic.Field(default="2026-10-08")
    dataset_version: str = pydantic.Field(default="v1.0")
    reviewers: List[str] = pydantic.Field(default_factory=list)


class NegativePatch(pydantic.BaseModel):
    name: str = pydantic.Field(description="Name or flaw category of this negative solution")
    patch: str = pydantic.Field(description="Unified diff of the flawed patch")
    expected_failure_type: str = pydantic.Field(description="Failure code e.g. F09_REGRESSION, F10_SECURITY_VIOLATION")


class BenchmarkTaskSchema(pydantic.BaseModel):
    """Strongly typed, versioned task schema for MA-SET Lab."""
    id: str = pydantic.Field(pattern=r"^BENCH-\d{3,}$", description="Task identifier, e.g. BENCH-001")
    version: int = pydantic.Field(default=1, ge=1)
    title: str = pydantic.Field(min_length=5)
    domain: str = pydantic.Field(default="backend")
    subcategory: str = pydantic.Field(default="general")
    language: str = pydantic.Field(default="python")
    framework: str = pydantic.Field(default="fastapi")
    difficulty: DifficultyConfig
    task_type: TaskType
    prompt: str = pydantic.Field(min_length=15, description="Instructions given to the agent")
    requirements: List[str] = pydantic.Field(min_length=1, description="Explicit functional requirements")
    constraints: ConstraintsConfig = pydantic.Field(default_factory=ConstraintsConfig)
    evaluation: EvaluationConfig = pydantic.Field(default_factory=EvaluationConfig)
    calibration: CalibrationConfig = pydantic.Field(default_factory=CalibrationConfig)
    metadata: MetadataConfig = pydantic.Field(default_factory=MetadataConfig)
    status: TaskStatus = pydantic.Field(default=TaskStatus.ACCEPTED)

    # Golden & Negative Solutions for Ground Truth Evaluation
    golden_patch: Optional[str] = pydantic.Field(default=None, description="Trusted reference solution patch")
    negative_patches: List[NegativePatch] = pydantic.Field(default_factory=list, description="Flawed patches to validate evaluator sensitivity")

    @property
    def description(self) -> str:
        return self.prompt

    model_config = pydantic.ConfigDict(extra="ignore", use_enum_values=True)

