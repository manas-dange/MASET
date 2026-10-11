"""
P2.1 — Code Index (ripgrep + ast)
===================================
Gives agents a fast, scoped view of the codebase so they never need to
read every file; they see only what is relevant to the task.

Two backends:
  ripgrep (rg)  — text pattern search; used when `rg` is on PATH.
  Python grep   — stdlib fallback using pathlib + re; no external tools.

Symbol extraction uses Python's built-in ``ast`` module (zero dependencies).
This handles Python files; other languages can be added later.

Public API
----------
    idx = CodeIndex(root=Path("demo_target"))

    # Text search
    results = idx.search("validate_signup")
    # → [SearchResult(file="app.py", line=18, snippet="def validate_signup...")]

    # Find all functions/classes in a file
    symbols = idx.symbols("demo_target/app.py")
    # → [Symbol(name="signup", kind="function", line=30), ...]

    # Find which files reference a symbol
    refs = idx.references("legacy_billing", root=Path("."))
    # → ["demo_target/app.py"]

    # List protected files touched by a set of changed paths
    protected = idx.flag_protected(changed=["demo_target/app.py"],
                                   deny_list=["demo_target/legacy_billing.py"])
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    file: str
    line: int
    snippet: str


@dataclass
class Symbol:
    name: str
    kind: str          # "function" | "class" | "method"
    line: int
    file: str = ""


# ---------------------------------------------------------------------------
# CodeIndex
# ---------------------------------------------------------------------------

class CodeIndex:
    """
    Lightweight code search and symbol extraction for the Architect agent.

    Parameters
    ----------
    root : Path
        Directory to search (default: current working directory).
    include_patterns : list[str]
        Glob patterns for files to include (e.g. ``["*.py"]``).
    exclude_dirs : list[str]
        Directory names to skip (e.g. ``[".venv", "__pycache__"]``).
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        project_root: Optional[Path] = None,
        deny_list: Optional[List[str]] = None,
        include_patterns: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None,
    ):
        target_root = project_root or root or Path(".")
        self._root = target_root.resolve()
        self._deny_list = deny_list or []
        self._include = include_patterns or ["*.py"]
        self._exclude = exclude_dirs or [".venv", "__pycache__", ".git", ".ma_set_cache"]
        self._has_rg = self._check_rg()

    # ------------------------------------------------------------------
    # Text search
    # ------------------------------------------------------------------

    def search(
        self,
        pattern: str,
        path: Optional[str] = None,
        max_results: int = 50,
    ) -> List[SearchResult]:
        """
        Search for *pattern* (plain text or regex) in the codebase.
        Returns up to *max_results* matches.
        """
        search_root = (self._root / path) if path else self._root

        if self._has_rg:
            return self._rg_search(pattern, search_root, max_results)
        return self._py_search(pattern, search_root, max_results)

    def references(
        self,
        symbol: str,
        path: Optional[str] = None,
        max_results: int = 30,
    ) -> List[str]:
        """Return a deduplicated list of file paths that reference *symbol*."""
        results = self.search(symbol, path=path, max_results=max_results)
        seen = []
        for r in results:
            if r.file not in seen:
                seen.append(r.file)
        return seen

    # ------------------------------------------------------------------
    # Symbol extraction
    # ------------------------------------------------------------------

    def symbols(self, file_path: str) -> List[Symbol]:
        """
        Return all top-level functions and classes (and their methods)
        defined in *file_path* using Python's ``ast`` module.
        """
        full = self._root / file_path
        if not full.exists():
            return []
        try:
            source = full.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(full))
        except SyntaxError:
            return []

        results: List[Symbol] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                results.append(Symbol(
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    file=file_path,
                ))
            elif isinstance(node, ast.ClassDef):
                results.append(Symbol(
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    file=file_path,
                ))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        results.append(Symbol(
                            name=f"{node.name}.{item.name}",
                            kind="method",
                            line=item.lineno,
                            file=file_path,
                        ))
        return sorted(results, key=lambda s: s.line)

    def list_files(self, path: Optional[str] = None) -> List[str]:
        """
        Return all Python files under *path* (relative to root),
        excluding ignored directories.
        """
        search_root = (self._root / path) if path else self._root
        files = []
        for pat in self._include:
            for p in search_root.rglob(pat):
                if not any(ex in p.parts for ex in self._exclude):
                    rel = str(p.relative_to(self._root))
                    files.append(rel)
        return sorted(files)

    # ------------------------------------------------------------------
    # Impact analysis helper
    # ------------------------------------------------------------------

    @staticmethod
    def flag_protected(
        changed: List[str],
        deny_list: List[str],
    ) -> List[str]:
        """
        Return the subset of *changed* paths that appear in *deny_list*.
        """
        flagged = []
        for path in changed:
            for denied in deny_list:
                if denied.endswith("/"):
                    if path.startswith(denied.rstrip("/")):
                        flagged.append(path)
                        break
                elif path == denied:
                    flagged.append(path)
                    break
        return flagged

    # ------------------------------------------------------------------
    # Internal: ripgrep backend
    # ------------------------------------------------------------------

    def _rg_search(
        self, pattern: str, root: Path, max_results: int
    ) -> List[SearchResult]:
        exclude_args = []
        for ex in self._exclude:
            exclude_args += ["--glob", f"!{ex}/**"]

        try:
            proc = subprocess.run(
                ["rg", "--line-number", "--no-heading", "--max-count", "5",
                 "--max-filesize", "1M",
                 *exclude_args, pattern, str(root)],
                capture_output=True, text=True, timeout=10,
            )
            return self._parse_rg_output(proc.stdout, max_results)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return self._py_search(pattern, root, max_results)

    @staticmethod
    def _parse_rg_output(output: str, max_results: int) -> List[SearchResult]:
        results = []
        for line in output.splitlines():
            # format: path:line_num:snippet
            parts = line.split(":", 2)
            if len(parts) >= 3:
                results.append(SearchResult(
                    file=parts[0],
                    line=int(parts[1]) if parts[1].isdigit() else 0,
                    snippet=parts[2].strip()[:120],
                ))
            if len(results) >= max_results:
                break
        return results

    # ------------------------------------------------------------------
    # Internal: Python fallback backend
    # ------------------------------------------------------------------

    def _py_search(
        self, pattern: str, root: Path, max_results: int
    ) -> List[SearchResult]:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        results = []
        for pat in self._include:
            for file in root.rglob(pat):
                if any(ex in file.parts for ex in self._exclude):
                    continue
                try:
                    for i, line in enumerate(
                        file.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                    ):
                        if regex.search(line):
                            results.append(SearchResult(
                                file=str(file.relative_to(self._root)),
                                line=i,
                                snippet=line.strip()[:120],
                            ))
                            if len(results) >= max_results:
                                return results
                except OSError:
                    continue
        return results

    @staticmethod
    def _check_rg() -> bool:
        try:
            subprocess.run(["rg", "--version"], capture_output=True, timeout=3)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    idx = CodeIndex(root=Path("demo_target"))
    print("=== search: 'signup' ===")
    for r in idx.search("signup"):
        print(f"  {r.file}:{r.line}  {r.snippet[:60]}")

    print("\n=== symbols in app.py ===")
    for s in idx.symbols("app.py"):
        print(f"  [{s.kind}] {s.name}  (line {s.line})")

    print("\n=== files ===")
    for f in idx.list_files():
        print(f"  {f}")

    print("\n=== protect check ===")
    flagged = CodeIndex.flag_protected(
        changed=["app.py", "legacy_billing.py"],
        deny_list=["legacy_billing.py"],
    )
    print(f"  Protected files touched: {flagged}")
