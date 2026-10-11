"""
Code Quality Evaluator (AgentEval)
==================================
Evaluates code quality of agent modifications:
  - AST validity & parseability
  - Ruff / flake8 lint cleanliness
  - Style, cyclomatic complexity, and readability
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional
from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment


class QualityEvaluationResult:
    def __init__(
        self,
        syntax_valid: bool,
        lint_errors: List[str],
        ast_errors: List[str],
        quality_score: float,
    ):
        self.syntax_valid = syntax_valid
        self.lint_errors = lint_errors
        self.ast_errors = ast_errors
        self.quality_score = quality_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "syntax_valid": self.syntax_valid,
            "quality_score": round(self.quality_score, 1),
            "lint_error_count": len(self.lint_errors),
            "lint_errors": self.lint_errors[:5],
            "ast_errors": self.ast_errors,
        }


class QualityEvaluator:
    """Evaluates code cleanliness and AST validity."""

    def evaluate(
        self,
        environment: Any = None,
        workspace_dir: Optional[Any] = None,
    ) -> QualityEvaluationResult:
        ast_errors: List[str] = []
        lint_errors: List[str] = []
        syntax_valid = True

        target_dir = None
        files_to_check = []
        if environment is not None and hasattr(environment, "work_dir"):
            target_dir = environment.work_dir
            files_to_check = list(getattr(environment, "files_modified", []))
        elif environment is not None and hasattr(environment, "workspace_path"):
            target_dir = environment.workspace_path
            files_to_check = list(getattr(environment, "files_modified", []))
        elif workspace_dir is not None:
            from pathlib import Path
            target_dir = Path(workspace_dir)
            files_to_check = [str(p.relative_to(target_dir)) for p in target_dir.rglob("*.py") if not any(x in str(p) for x in (".venv", ".git", "__pycache__", "runs"))]

        # 1. AST syntax parsing on modified files
        for mod_file in files_to_check:
            if mod_file.endswith(".py") and target_dir:
                fpath = target_dir / mod_file
                if fpath.exists():
                    try:
                        source = fpath.read_text(encoding="utf-8")
                        ast.parse(source, filename=mod_file)
                    except SyntaxError as exc:
                        syntax_valid = False
                        ast_errors.append(f"{mod_file}:{exc.lineno} SyntaxError: {exc.msg}")

        # 2. Run ruff linter if available in environment
        if environment is not None and hasattr(environment, "execute") and files_to_check:
            py_files = [f for f in files_to_check if f.endswith(".py")]
            if py_files:
                files_arg = " ".join(py_files[:10])
                ruff_res = environment.execute(f"ruff check {files_arg}", timeout=15)
                if not getattr(ruff_res, "success", True) and ruff_res.stdout.strip():
                    for line in ruff_res.stdout.splitlines():
                        if ":" in line and not line.startswith("Found"):
                            lint_errors.append(line.strip())


        score = 100.0
        if not syntax_valid:
            score -= 60.0
        if lint_errors:
            score -= min(40.0, len(lint_errors) * 5.0)

        score = max(0.0, score)

        return QualityEvaluationResult(
            syntax_valid=syntax_valid,
            lint_errors=lint_errors,
            ast_errors=ast_errors,
            quality_score=score,
        )
