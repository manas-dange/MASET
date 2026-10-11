"""
P1.2 — Sandboxed Command Runner
=================================
Runs shell commands (pytest, ruff, git diff …) inside a disposable copy
of the demo target.  The copy is discarded after each task, so a buggy
agent cannot leave the real workspace in a broken state.

Implementation
--------------
We use ``tempfile.TemporaryDirectory`` + ``shutil.copytree`` to create an
isolated workspace.  This gives the same isolation guarantees as a git
worktree without requiring the demo target to be a real git repo during
Phase 0 / Phase 1 development.

When Docker/Colima is available (Phase 2 option), this class can be
swapped for a container-based runner without changing any agent code.

Usage
-----
    from ma_set.protection.sandbox import Sandbox

    with Sandbox(source_dir=Path("demo_target"), run_id="r1") as sb:
        result = sb.run(["pytest", "tests/", "-v"])
        print(result.stdout)
        print("exit code:", result.exit_code)
        # On __exit__ the temp dir is deleted automatically
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class CommandResult:
    """Structured result from a sandboxed command."""
    command: List[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def summary(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return (
            f"[{status}] exit={self.exit_code} "
            f"({self.duration_s:.2f}s)\n"
            f"stdout: {self.stdout[:500]}\n"
            f"stderr: {self.stderr[:200]}"
        )


class Sandbox:
    """
    Context manager that provides an isolated, disposable workspace.

    Parameters
    ----------
    source_dir : Path
        The directory to copy into the sandbox (e.g. the project root or
        just the demo_target folder).
    run_id : str
        Used in event emission and temp-dir naming for traceability.
    python_executable : str
        Path to the Python interpreter to use inside the sandbox.
        Defaults to the current venv interpreter.
    event_callback : callable, optional
        Receives a dict for every SANDBOX_COMMAND and SANDBOX_RESULT event.
    node : str
        IDEF0 node tag for event emission.
    agent : str
        Agent name for event emission.
    """

    def __init__(
        self,
        source_dir: Path,
        run_id: str = "no-run",
        python_executable: Optional[str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A4",
        agent: str = "tester",
    ):
        self._source = source_dir.resolve()
        self._run_id = run_id
        self._python = python_executable or sys.executable
        self._cb = event_callback
        self._node = node
        self._agent = agent

        self._tmp_dir: Optional[Path] = None
        self._work_dir: Optional[Path] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Sandbox":
        import tempfile
        tmp = tempfile.mkdtemp(prefix=f"maset_{self._run_id[:8]}_")
        self._tmp_dir = Path(tmp)
        # Copy source into the sandbox
        dest = self._tmp_dir / self._source.name
        shutil.copytree(str(self._source), str(dest))
        self._work_dir = dest
        self._emit("tool_call", {
            "action": "sandbox_created",
            "source": str(self._source),
            "sandbox": str(self._work_dir),
        })
        return self

    def __exit__(self, *_) -> None:
        if self._tmp_dir and self._tmp_dir.exists():
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        self._emit("tool_call", {"action": "sandbox_discarded"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def work_dir(self) -> Path:
        if self._work_dir is None:
            raise RuntimeError("Sandbox not entered — use as a context manager.")
        return self._work_dir

    def run(
        self,
        command: List[str],
        timeout: int = 120,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """
        Execute *command* inside the sandboxed work directory.

        Parameters
        ----------
        command : list[str]
            The command and its arguments.
            Use ``[self.python, "-m", "pytest", ...]`` for Python tools.
        timeout : int
            Maximum wall-clock seconds before the process is killed.
        extra_env : dict, optional
            Additional environment variables merged on top of the current env.
        """
        import os

        if self._work_dir is None:
            raise RuntimeError("Sandbox not entered — use as a context manager.")

        env = {**os.environ, **(extra_env or {})}
        # Replace 'python' / 'python3' / 'pytest' with the venv binaries
        cmd = self._resolve_command(command)

        self._emit("sandbox_command", {
            "command": cmd,
            "cwd": str(self._work_dir),
        })

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self._work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            duration = time.monotonic() - start
            result = CommandResult(
                command=cmd,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_s=round(duration, 3),
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            result = CommandResult(
                command=cmd,
                exit_code=-1,
                stdout="",
                stderr=f"TIMEOUT after {timeout}s",
                duration_s=round(duration, 3),
            )
        except FileNotFoundError as exc:
            duration = time.monotonic() - start
            result = CommandResult(
                command=cmd,
                exit_code=-1,
                stdout="",
                stderr=f"Command not found: {exc}",
                duration_s=round(duration, 3),
            )

        self._emit("sandbox_result", {
            "command": cmd,
            "exit_code": result.exit_code,
            "duration_s": result.duration_s,
            "stdout_snippet": result.stdout[:500],
        })
        return result

    def apply_patch(self, relative_path: str, content: str) -> None:
        """
        Write *content* to *relative_path* inside the sandbox.
        Does NOT go through PathFilter — the filter is applied before this
        method is called, in the Developer agent.
        """
        target = self._work_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, relative_path: str) -> str:
        """Read a file from the sandbox."""
        return (self._work_dir / relative_path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_command(self, command: List[str]) -> List[str]:
        """
        Swap bare 'python', 'python3', 'pytest', 'ruff' with the venv paths.
        """
        venv_bin = Path(self._python).parent
        replacements = {
            "python":  self._python,
            "python3": self._python,
            "pytest":  str(venv_bin / "pytest"),
            "ruff":    str(venv_bin / "ruff"),
        }
        resolved = []
        for i, token in enumerate(command):
            if i == 0 and token in replacements:
                resolved.append(replacements[token])
            else:
                resolved.append(token)
        return resolved

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._cb:
            try:
                self._cb({
                    "run_id": self._run_id,
                    "node": self._node,
                    "agent": self._agent,
                    "event_type": event_type,
                    "payload": payload,
                })
            except Exception:
                pass
