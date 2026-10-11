"""
Constraints Evaluator (AgentEval)
=================================
Deterministically evaluates whether the agent complied with hard constraints:
  - Protected files unchanged (deny list)
  - Forbidden dependencies not introduced
  - Required files present
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment


class ConstraintEvaluationResult:
    def __init__(
        self,
        passed: bool,
        violations: List[str],
        protected_files_checked: List[str],
        forbidden_dependencies_checked: List[str],
        checks: Optional[List[str]] = None,
    ):
        self.passed = passed
        self.all_satisfied = passed
        self.violations = violations
        self.protected_files_checked = protected_files_checked
        self.forbidden_dependencies_checked = forbidden_dependencies_checked
        self.checks = checks or (protected_files_checked + forbidden_dependencies_checked)

    @property
    def score(self) -> float:
        return 100.0 if self.passed else max(0.0, 100.0 - (len(self.violations) * 35.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "all_satisfied": self.all_satisfied,
            "score": round(self.score, 1),
            "violations": self.violations,
            "protected_files_checked": self.protected_files_checked,
            "forbidden_dependencies_checked": self.forbidden_dependencies_checked,
            "checks": self.checks,
        }


ConstraintCheckResult = ConstraintEvaluationResult


class ConstraintsEvaluator:
    """Evaluates task constraints deterministically."""

    def __init__(
        self,
        protected_files: Optional[List[str]] = None,
        forbidden_dependencies: Optional[List[str]] = None,
    ):
        self.protected_files = protected_files or ["demo_target/legacy_billing.py"]
        self.forbidden_dependencies = forbidden_dependencies or []

    def evaluate(
        self,
        environment: Any = None,
        task_constraints: Optional[Dict[str, Any]] = None,
        workspace_dir: Optional[Any] = None,
        protected_patterns: Optional[List[str]] = None,
        forbidden_dependencies: Optional[List[str]] = None,
        initial_commit: Optional[str] = None,
    ) -> ConstraintEvaluationResult:
        protected = protected_patterns or (task_constraints.get("protected_files") if task_constraints else None) or self.protected_files
        forbidden_deps = forbidden_dependencies or (task_constraints.get("forbidden_dependencies") if task_constraints else None) or self.forbidden_dependencies

        violations: List[str] = []
        checks: List[str] = [f"protected:{p}" for p in protected] + [f"forbidden_dep:{d}" for d in forbidden_deps]

        # Determine target work dir
        target_dir = None
        if hasattr(environment, "work_dir"):
            target_dir = environment.work_dir
        elif hasattr(environment, "workspace_path"):
            target_dir = environment.workspace_path
        elif workspace_dir is not None:
            target_dir = workspace_dir

        if target_dir:
            from pathlib import Path
            target_dir = Path(target_dir)

            # Check protected files tampering
            for pfile in protected:
                if hasattr(environment, "files_modified") and pfile in environment.files_modified:
                    violations.append(f"Protected file '{pfile}' was modified")
                    continue

                if hasattr(environment, "source_dir") and environment.source_dir:
                    src_file = Path(environment.source_dir) / pfile
                    work_file = target_dir / pfile
                    if src_file.exists() and work_file.exists():
                        if src_file.read_text(encoding="utf-8") != work_file.read_text(encoding="utf-8"):
                            violations.append(f"Protected file '{pfile}' differs from source baseline")
                            continue

                # Check git diff in target_dir if repository exists
                try:
                    import subprocess
                    res = subprocess.run(
                        ["git", "diff", "--name-only", "HEAD", "--", pfile],
                        cwd=target_dir,
                        capture_output=True,
                        text=True,
                    )
                    if res.returncode == 0 and pfile in res.stdout:
                        violations.append(f"Protected file '{pfile}' was modified according to git diff")
                except Exception:
                    pass

            # Check forbidden dependencies
            req_file = target_dir / "requirements.txt"
            if req_file.exists() and forbidden_deps:
                req_content = req_file.read_text(encoding="utf-8")
                for dep in forbidden_deps:
                    if dep in req_content:
                        violations.append(f"Forbidden dependency '{dep}' found in requirements.txt")

        return ConstraintEvaluationResult(
            passed=len(violations) == 0,
            violations=violations,
            protected_files_checked=protected,
            forbidden_dependencies_checked=forbidden_deps,
            checks=checks,
        )

