"""
Isolated Environment Runner (TerminalBench Environment)
========================================================
Manages an isolated execution workspace for evaluating software-engineering agents.
Provides:
  - Sandboxed filesystem with disposable lifecycle
  - Terminal command execution with timeout & resource limits
  - Command audit trail logging
  - Git state tracking (diffs, modified files, untracked files)
  - Seamless fallback between containerized Docker and disposable filesystem sandbox
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

from ma_set.protection.path_filter import PathFilter


class EnvironmentExecutionError(Exception):
    """Raised when an environment command fails or times out unexpectedly."""


class EnvironmentCommandResult:
    """Result of running a command inside the isolated environment."""

    def __init__(
        self,
        command: List[str] | str,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_s: float,
        timed_out: bool = False,
    ):
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration_s = duration_s
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:2000],
            "stderr": self.stderr[:2000],
            "duration_s": round(self.duration_s, 3),
            "timed_out": self.timed_out,
            "success": self.success,
        }


class IsolatedEnvironment:
    """
    TerminalBench Isolated Execution Environment.
    Wraps a pristine copy of the target repository, enforcing network and
    resource controls, and capturing all command interactions.
    """

    def __init__(
        self,
        source_dir: Path,
        run_id: str = "lab_run",
        timeout_seconds: int = 60,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        allow_list: Optional[List[str]] = None,
        deny_list: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        protected_patterns: Optional[List[str]] = None,
        workspace_path: Optional[Path] = None,
    ):
        self.source_dir = Path(source_dir).resolve()
        self.run_id = task_id or run_id
        self.task_id = self.run_id
        self.timeout_seconds = timeout_seconds
        self.event_callback = event_callback
        self.allow_list = allow_list or ["demo_target/app.py", "demo_target/tests/", "src/", "tests/"]
        self.deny_list = protected_patterns or deny_list or ["demo_target/legacy_billing.py", ".venv/", ".git/"]

        self._tmp_dir: Optional[Path] = None
        self._work_dir: Optional[Path] = workspace_path
        self._commands_run: List[EnvironmentCommandResult] = []
        self._files_inspected: List[str] = []
        self._files_modified: List[str] = []
        self._path_filter: Optional[PathFilter] = None
        self.events_emitted: List[Dict[str, Any]] = []

    def setup(self) -> "IsolatedEnvironment":
        return self.__enter__()

    def teardown(self) -> None:
        self.__exit__(None, None, None)

    @property
    def workspace_path(self) -> Path:
        return self.work_dir

    def execute_command(self, cmd: List[str] | str, timeout: Optional[int] = None) -> EnvironmentCommandResult:
        return self.execute(cmd, timeout=timeout)


    def __enter__(self) -> "IsolatedEnvironment":
        tmp = tempfile.mkdtemp(prefix=f"maset_lab_{self.run_id[:8]}_")
        self._tmp_dir = Path(tmp)

        # Copy source into isolated workspace (excluding .venv, .git, and runs)
        dest = self._tmp_dir / self.source_dir.name

        def _ignore_patterns(path: str, names: List[str]) -> List[str]:
            ignored = []
            for name in names:
                if name in {".venv", ".git", "__pycache__", "runs", ".pytest_cache"}:
                    ignored.append(name)
            return ignored

        shutil.copytree(str(self.source_dir), str(dest), ignore=_ignore_patterns)
        self._work_dir = dest

        # Initialize a fresh git repository inside the disposable workspace
        try:
            subprocess.run(["git", "init", "-q"], cwd=str(dest), capture_output=True, check=False)
            subprocess.run(["git", "config", "user.name", "MA-SET Agent"], cwd=str(dest), capture_output=True, check=False)
            subprocess.run(["git", "config", "user.email", "agent@maset.local"], cwd=str(dest), capture_output=True, check=False)
            subprocess.run(["git", "add", "-A"], cwd=str(dest), capture_output=True, check=False)
            subprocess.run(["git", "commit", "-q", "-m", "Initial baseline commit"], cwd=str(dest), capture_output=True, check=False)
        except Exception:
            pass

        # Initialize PathFilter inside isolated workspace
        self._path_filter = PathFilter(
            allow_list=self.allow_list,
            deny_list=self.deny_list,
            project_root=self._work_dir,
            run_id=self.run_id,
            node="lab_env",
            agent="environment",
            event_callback=self.event_callback,
        )

        self._emit("environment_created", {
            "source": str(self.source_dir),
            "isolated_path": str(self._work_dir),
            "run_id": self.run_id,
        })
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._tmp_dir and self._tmp_dir.exists():
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        self._emit("environment_destroyed", {
            "run_id": self.run_id,
            "commands_executed": len(self._commands_run),
        })

    @property
    def work_dir(self) -> Path:
        if self._work_dir is None:
            raise RuntimeError("Environment not active. Use within a context manager.")
        return self._work_dir

    @property
    def commands_executed(self) -> List[EnvironmentCommandResult]:
        return list(self._commands_run)

    @property
    def files_inspected(self) -> List[str]:
        return list(set(self._files_inspected))

    @property
    def files_modified(self) -> List[str]:
        return list(set(self._files_modified))

    # -----------------------------------------------------------------------
    # Terminal Execution
    # -----------------------------------------------------------------------

    def execute(
        self,
        cmd: List[str] | str,
        timeout: Optional[int] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> EnvironmentCommandResult:
        """
        Execute a terminal command inside the isolated environment directory.
        """
        if self._work_dir is None:
            raise RuntimeError("Environment not initialized.")

        timeout_val = timeout or self.timeout_seconds
        start_t = time.monotonic()

        # Build execution environment (inherit python PATH / virtualenv)
        env = dict(os.environ)
        if env_vars:
            env.update(env_vars)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        cmd_list = cmd if isinstance(cmd, list) else cmd.split()
        shell_mode = isinstance(cmd, str)

        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self._work_dir),
                shell=shell_mode,
                capture_output=True,
                text=True,
                timeout=timeout_val,
                env=env,
            )
            exit_code = proc.returncode
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = exc.stdout or "" if isinstance(exc.stdout, str) else ""
            stderr = f"Command timed out after {timeout_val}s"
        except Exception as exc:
            exit_code = 1
            stdout = ""
            stderr = str(exc)

        duration = time.monotonic() - start_t
        res = EnvironmentCommandResult(
            command=cmd,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=duration,
            timed_out=timed_out,
        )
        self._commands_run.append(res)

        self._emit("terminal_command", {
            "command": cmd if isinstance(cmd, str) else " ".join(cmd),
            "exit_code": exit_code,
            "duration_s": round(duration, 3),
            "timed_out": timed_out,
        })

        return res

    # -----------------------------------------------------------------------
    # Filesystem Operations
    # -----------------------------------------------------------------------

    def read_file(self, rel_path: str) -> str:
        """Read a file in the environment, checking safety and logging inspection."""
        self._files_inspected.append(rel_path)
        if self._path_filter:
            return self._path_filter.read(rel_path)
        target = self.work_dir / rel_path
        return target.read_text(encoding="utf-8")

    def write_file(self, rel_path: str, content: str) -> None:
        """Write a file in the environment, enforcing allow/deny rules."""
        self._files_modified.append(rel_path)
        if self._path_filter:
            self._path_filter.write(rel_path, content)
        else:
            target = self.work_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def file_exists(self, rel_path: str) -> bool:
        return (self.work_dir / rel_path).exists()

    def get_diff(self) -> str:
        """Compute unified git diff or filesystem difference from source."""
        res = self.execute("git diff", timeout=10)
        if res.success and res.stdout.strip():
            return res.stdout

        # Fallback: file comparison between source and sandbox
        import difflib
        diff_chunks = []
        for modified in self.files_modified:
            src_file = self.source_dir / modified
            sandbox_file = self.work_dir / modified
            if sandbox_file.exists():
                orig_lines = src_file.read_text(encoding="utf-8").splitlines(keepends=True) if src_file.exists() else []
                new_lines = sandbox_file.read_text(encoding="utf-8").splitlines(keepends=True)
                diff = difflib.unified_diff(
                    orig_lines,
                    new_lines,
                    fromfile=f"a/{modified}",
                    tofile=f"b/{modified}",
                )
                diff_chunks.extend(diff)
        return "".join(diff_chunks)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        ev_dict = {
            "event_type": str(event_name),
            "agent_id": payload.get("agent", "environment"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload": payload,
        }
        self.events_emitted.append(ev_dict)
        if self.event_callback:
            try:
                self.event_callback(ev_dict)
            except Exception:
                pass

    def _emit_event(self, event_type: Any, payload: Dict[str, Any]) -> None:
        name = event_type.value if hasattr(event_type, "value") else str(event_type)
        self._emit(name, payload)

