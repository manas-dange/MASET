"""MA-SET Lab: Task Validator.

Performs static quality assurance and schema validation on benchmark task definitions:
- Schema structural validity
- Prompt clarity and completeness
- Requirements consistency
- Protected path integrity
- Anti-leakage and contamination checks (checking for exposed answers or golden diffs)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
import pydantic

from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema


@dataclass
class ValidationIssue:
    severity: str  # "ERROR" or "WARNING"
    field: str
    message: str


@dataclass
class TaskValidationResult:
    task_id: str
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[str]:
        return [i.message for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> List[str]:
        return [i.message for i in self.issues if i.severity == "WARNING"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class TaskValidator:
    """Validates task schemas and audits for contamination and vagueness."""

    LEAKAGE_MARKERS = [
        "diff --git",
        "+++ b/",
        "--- a/",
        "SECRET_KEY_FOR_BENCHMARK",
        "SOLUTION:",
        "PATCH_START",
    ]

    def validate_dict(self, data: Dict[str, Any]) -> TaskValidationResult:
        task_id = str(data.get("id", "UNKNOWN"))
        issues: List[ValidationIssue] = []

        # 1. Pydantic validation
        try:
            task = BenchmarkTaskSchema(**data)
        except pydantic.ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        field=loc,
                        message=f"{loc}: {err.get('msg')}",
                    )
                )
            return TaskValidationResult(task_id=task_id, is_valid=False, issues=issues)

        # 2. Prompt quality
        prompt = task.prompt.strip()
        if len(prompt) < 25:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    field="prompt",
                    message="Prompt is too short (< 25 characters) to specify a real engineering task.",
                )
            )

        # 3. Requirements check
        if not task.requirements:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    field="requirements",
                    message="At least one explicit requirement must be defined.",
                )
            )

        # 4. Contamination check
        for marker in self.LEAKAGE_MARKERS:
            if marker in prompt:
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        field="prompt",
                        message=f"Prompt contains potential solution leakage marker: '{marker}'",
                    )
                )

        # 5. Golden solution check
        if not task.golden_patch:
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    field="golden_patch",
                    message="Task does not include a verified golden reference patch.",
                )
            )

        # 6. Evaluation test commands
        if not task.evaluation.functional_tests:
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    field="evaluation.functional_tests",
                    message="No explicit functional test commands specified; default runner tests will be inferred.",
                )
            )

        is_valid = not any(i.severity == "ERROR" for i in issues)
        return TaskValidationResult(task_id=task.id, is_valid=is_valid, issues=issues)

    def validate_file(self, file_path: Path) -> TaskValidationResult:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return TaskValidationResult(
                    task_id=file_path.stem,
                    is_valid=False,
                    issues=[ValidationIssue(severity="ERROR", field="file", message="File does not contain a YAML mapping")],
                )
            return self.validate_dict(data)
        except Exception as e:
            return TaskValidationResult(
                task_id=file_path.stem,
                is_valid=False,
                issues=[ValidationIssue(severity="ERROR", field="file", message=f"Failed to read/parse YAML: {e}")],
            )
