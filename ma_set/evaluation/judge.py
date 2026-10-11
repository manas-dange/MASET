"""MA-SET Lab: Evidence-Based LLM-as-Judge Subsystem.

Strictly reserved for subjective / semantic criteria:
- Maintainability
- Implementation intent
- Quality of explanation / comments
- Semantic style

RULE: Never use LLM judge for deterministic facts (tests passing, files existing, exit codes).
RULE: Every judgment MUST supply concrete, verifiable evidence strings. Generic "looks good" ratings are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pydantic


class JudgeVerdict(pydantic.BaseModel):
    """Structured, evidence-grounded verdict from an LLM judge."""
    task_id: str
    criterion: str
    score: float = pydantic.Field(ge=0.0, le=100.0, description="Normalized score 0-100")
    confidence: float = pydantic.Field(ge=0.0, le=1.0, description="Confidence in verdict")
    evidence: List[str] = pydantic.Field(min_length=1, description="List of concrete factual citations or diff references")
    failure_type: Optional[str] = None
    reasoning: Optional[str] = None

    @pydantic.field_validator("evidence")
    @classmethod
    def validate_evidence_substantive(cls, v: List[str]) -> List[str]:
        banned = {"looks good", "passed", "seems fine", "ok", "good job", "n/a"}
        cleaned = [e.strip() for e in v if e.strip()]
        if not cleaned:
            raise ValueError("Evidence list cannot be empty or whitespace only")
        for item in cleaned:
            if item.lower() in banned or len(item) < 10:
                raise ValueError(f"Evidence '{item}' is too vague; provide substantive diff/AST references")
        return cleaned


class SemanticJudge:
    """Evaluates subjective criteria using deterministic rules with optional LLM invocation."""

    SUBJECTIVE_CRITERIA = {
        "maintainability",
        "implementation_intent",
        "code_clarity",
        "explanation_quality",
    }

    def judge_heuristic(
        self,
        task_id: str,
        criterion: str,
        diff: str,
        commit_message: str = "",
    ) -> JudgeVerdict:
        """Deterministic heuristic fallback when no LLM key is configured."""
        evidence: List[str] = []
        score = 80.0

        if not diff.strip():
            return JudgeVerdict(
                task_id=task_id,
                criterion=criterion,
                score=0.0,
                confidence=1.0,
                evidence=["No code diff produced by agent."],
                failure_type="F15_UNDERIMPLEMENTATION",
                reasoning="Agent generated no changes.",
            )

        lines = diff.splitlines()
        additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))

        if criterion == "maintainability":
            has_comments = any("#" in line or '"""' in line for line in lines if line.startswith("+"))
            if has_comments:
                evidence.append("Patch includes inline comments or docstrings in added lines.")
                score += 10.0
            else:
                evidence.append("Patch adds logic without supplementary docstrings.")
                score -= 10.0

            if additions > 300:
                evidence.append(f"Large diff size (+{additions} lines) may impair modularity.")
                score -= 20.0
            else:
                evidence.append(f"Concise, focused diff (+{additions}/-{deletions} lines).")
                score += 10.0

        elif criterion == "implementation_intent":
            if commit_message and len(commit_message) > 15:
                evidence.append(f"Detailed commit message provided: '{commit_message[:60]}...'")
                score += 15.0
            else:
                evidence.append("Sparse or missing commit message for solution intent.")
                score -= 10.0

        else:
            evidence.append(f"Heuristic evaluation of {criterion} based on {len(lines)} diff lines.")

        score = max(0.0, min(100.0, score))
        return JudgeVerdict(
            task_id=task_id,
            criterion=criterion,
            score=score,
            confidence=0.85,
            evidence=evidence,
            reasoning=f"Heuristic assessment for {criterion}",
        )
