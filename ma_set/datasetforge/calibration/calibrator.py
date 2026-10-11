"""MA-SET Lab: Difficulty Calibration Subsystem.

Empirically calibrates task difficulty based on observed pass rates across agent runs:
- Pass Rate >= 0.85 -> Difficulty 1 (Trivial)
- Pass Rate >= 0.65 -> Difficulty 2 (Easy)
- Pass Rate >= 0.40 -> Difficulty 3 (Moderate)
- Pass Rate >= 0.20 -> Difficulty 4 (Difficult)
- Pass Rate <  0.20 -> Difficulty 5 (Expert)

Ensures benchmark difficulty labels possess empirical meaning rather than subjective guesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema


@dataclass
class CalibrationRecord:
    task_id: str
    runs_count: int
    passes_count: int
    observed_pass_rate: float
    initial_difficulty: int
    recommended_difficulty: float
    status: str  # "CALIBRATED", "UNDER_SAMPLED", "MISALIGNED"
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "runs_count": self.runs_count,
            "passes_count": self.passes_count,
            "observed_pass_rate": round(self.observed_pass_rate, 4),
            "initial_difficulty": self.initial_difficulty,
            "recommended_difficulty": round(self.recommended_difficulty, 2),
            "status": self.status,
            "notes": self.notes,
        }


class DifficultyCalibrator:
    """Calibrates task difficulty using empirical benchmark results."""

    def compute_empirical_difficulty(self, pass_rate: float) -> float:
        """Map pass rate (0.0 - 1.0) to calibrated scale (1.0 - 5.0)."""
        if pass_rate >= 0.85:
            # 1.0 to 1.5
            return 1.0 + (1.0 - pass_rate) / 0.15 * 0.5
        elif pass_rate >= 0.65:
            # 1.5 to 2.5
            return 1.5 + (0.85 - pass_rate) / 0.20 * 1.0
        elif pass_rate >= 0.40:
            # 2.5 to 3.5
            return 2.5 + (0.65 - pass_rate) / 0.25 * 1.0
        elif pass_rate >= 0.20:
            # 3.5 to 4.5
            return 3.5 + (0.40 - pass_rate) / 0.20 * 1.0
        else:
            # 4.5 to 5.0
            return min(5.0, 4.5 + (0.20 - pass_rate) / 0.20 * 0.5)

    def calibrate(
        self,
        task: BenchmarkTaskSchema,
        results: List[bool],
    ) -> CalibrationRecord:
        runs = len(results)
        if runs == 0:
            return CalibrationRecord(
                task_id=task.id,
                runs_count=0,
                passes_count=0,
                observed_pass_rate=0.0,
                initial_difficulty=task.difficulty.initial,
                recommended_difficulty=float(task.difficulty.initial),
                status="UNDER_SAMPLED",
                notes="Zero evaluation runs available for calibration.",
            )

        passes = sum(1 for r in results if r)
        pass_rate = passes / runs
        recommended = self.compute_empirical_difficulty(pass_rate)

        # Update task configuration in-place
        task.calibration.runs = runs
        task.calibration.observed_pass_rate = round(pass_rate, 4)
        task.difficulty.calibrated = round(recommended, 2)

        diff_discrepancy = abs(float(task.difficulty.initial) - recommended)
        if runs < 3:
            status = "UNDER_SAMPLED"
            notes = f"Only {runs} runs evaluated; need at least 3 runs for high confidence."
        elif diff_discrepancy > 1.5:
            status = "MISALIGNED"
            notes = f"Large divergence between author rating ({task.difficulty.initial}) and empirical rating ({recommended:.1f})."
        else:
            status = "CALIBRATED"
            notes = f"Calibrated with pass rate {pass_rate:.1%} across {runs} runs."

        task.calibration.status = status

        return CalibrationRecord(
            task_id=task.id,
            runs_count=runs,
            passes_count=passes,
            observed_pass_rate=pass_rate,
            initial_difficulty=task.difficulty.initial,
            recommended_difficulty=recommended,
            status=status,
            notes=notes,
        )
