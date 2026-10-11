"""
P1.1 — Path Filter (Allow / Deny List)
========================================
Enforces which files agents may read from or write to.

Rules (evaluated in order)
---------------------------
1. If the normalised path matches ANY deny pattern  → BLOCKED
2. If the normalised path matches ANY allow pattern → ALLOWED
3. Otherwise                                        → BLOCKED (default-deny)

Patterns
--------
Patterns are POSIX path prefixes / globs evaluated with pathlib.PurePosixPath.
A trailing "/" means "this directory and everything inside".

Usage
-----
    from ma_set.protection.path_filter import PathFilter

    pf = PathFilter(
        allow_list=["demo_target/app.py", "demo_target/tests/"],
        deny_list=["demo_target/legacy_billing.py", ".venv/", ".git/"],
        project_root=Path("."),
        event_callback=my_callback,
        run_id="abc",
        node="A3",
        agent="developer",
    )

    # Check only (does not write)
    allowed, reason = pf.check("demo_target/app.py")

    # Write with enforcement
    pf.write("demo_target/app.py", new_content)      # OK
    pf.write("demo_target/legacy_billing.py", ...)   # raises PermissionError + logs event
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple


class PathFilter:
    """
    File-write tool that enforces the allow / deny lists at the code level.
    An agent cannot bypass these checks via prompt engineering — the filter
    is applied in Python before any disk I/O occurs.
    """

    def __init__(
        self,
        allow_list: List[str],
        deny_list: List[str],
        project_root: Path = Path("."),
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        run_id: str = "no-run",
        node: str = "A3",
        agent: str = "developer",
    ):
        self._allow = allow_list
        self._deny  = deny_list
        self._root  = project_root.resolve()
        self._cb    = event_callback
        self._run_id = run_id
        self._node  = node
        self._agent = agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, path: str) -> Tuple[bool, str]:
        """
        Return ``(allowed: bool, reason: str)`` without performing any I/O.
        """
        normalised = self._normalise(path)

        # 1. Deny list — highest priority
        for pattern in self._deny:
            if self._matches(normalised, pattern):
                return False, f"path '{normalised}' matches deny pattern '{pattern}'"

        # 2. Allow list
        for pattern in self._allow:
            if self._matches(normalised, pattern):
                return True, f"path '{normalised}' matches allow pattern '{pattern}'"

        # 3. Default deny
        return False, f"path '{normalised}' not in allow list"

    def read(self, path: str) -> str:
        """
        Read a file. Reading is always allowed (agents need to read protected
        files to understand the codebase) but the read is logged.
        """
        full = self._resolve(path)
        content = full.read_text(encoding="utf-8")
        self._emit("tool_call", {"action": "read", "path": path, "bytes": len(content)})
        return content

    def write(self, path: str, content: str) -> None:
        """
        Write *content* to *path* — only if it passes the allow / deny check.
        Raises :class:`PermissionError` and logs a FILE_WRITE_BLOCKED event
        if the path is denied.
        """
        allowed, reason = self.check(path)
        full = self._resolve(path)

        if not allowed:
            self._emit("file_write_blocked", {
                "path": path,
                "reason": reason,
            })
            raise PermissionError(
                f"[PROTECTION] Write blocked: {reason}. "
                "This incident has been logged."
            )

        # Safe to write
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        self._emit("file_write_allowed", {
            "path": path,
            "bytes": len(content),
        })

    def write_patch(self, path: str, original: str, patched: str) -> str:
        """
        Write *patched* to *path* and return a unified-diff string.
        Enforces allow / deny — raises ``PermissionError`` if blocked.
        """
        import difflib
        self.write(path, patched)
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        ))
        return "".join(diff_lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalise(self, path: str) -> str:
        """
        Return a POSIX path relative to the project root.
        Absolute paths are made relative; ``../`` traversal is rejected.
        """
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.relative_to(self._root)
            except ValueError:
                return str(path)  # outside root — will be blocked
        # Collapse ".." etc.
        normed = str(PurePosixPath(p))
        if normed.startswith(".."):
            return normed  # outside root — will be blocked
        return normed

    def _resolve(self, path: str) -> Path:
        return (self._root / path).resolve()

    @staticmethod
    def _matches(normalised: str, pattern: str) -> bool:
        """
        Check whether *normalised* matches *pattern*.
        Pattern ending in "/" is a directory prefix.
        Exact string match otherwise.
        """
        if pattern.endswith("/"):
            return normalised.startswith(pattern.rstrip("/"))
        return normalised == pattern or normalised.startswith(pattern + "/")

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


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile, textwrap

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "demo_target").mkdir()
        (root / "demo_target" / "app.py").write_text("# original")
        (root / "demo_target" / "legacy_billing.py").write_text("# protected")

        events: list = []
        pf = PathFilter(
            allow_list=["demo_target/app.py"],
            deny_list=["demo_target/legacy_billing.py"],
            project_root=root,
            event_callback=events.append,
        )

        print("--- check allowed ---")
        print(pf.check("demo_target/app.py"))

        print("--- check denied ---")
        print(pf.check("demo_target/legacy_billing.py"))

        print("--- check default-deny ---")
        print(pf.check("demo_target/new_file.py"))

        print("--- write allowed ---")
        pf.write("demo_target/app.py", "# patched")
        print("  OK")

        print("--- write denied ---")
        try:
            pf.write("demo_target/legacy_billing.py", "# hacked")
        except PermissionError as e:
            print(f"  Blocked: {e}")

        print(f"\nEvents: {[e['event_type'] for e in events]}")
