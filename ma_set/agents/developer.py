"""
P1.3 — Developer Agent
========================
Receives a design spec, calls the model adapter to generate code changes,
then applies those changes through the PathFilter.

In **stub mode** the agent applies a hard-coded patch that fixes the known
input-validation bug in demo_target/app.py, converting the three XFAIL
baseline tests into real passing tests.

In **real LLM mode** the agent sends a structured prompt and parses the
returned diff / code block.

Events emitted (P1.6)
---------------------
  AGENT_STARTED   — at the top of run()
  TOOL_CALL       — before each file read / write
  TOOL_RESULT     — after each file read / write
  FILE_WRITE_ALLOWED / FILE_WRITE_BLOCKED  — from PathFilter
  DIFF_PRODUCED   — when the diff is ready
  AGENT_FINISHED  — at the bottom of run()
  AGENT_ESCALATED — if an unrecoverable error occurs
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.model.adapter import ModelAdapter
from ma_set.protection.path_filter import PathFilter


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DeveloperResult:
    success: bool
    diff: str                        # unified-diff string (may be empty on failure)
    files_changed: List[str]
    patched_contents: Dict[str, str] # path -> new file content
    error: str = ""                  # populated on failure


# ---------------------------------------------------------------------------
# Stub patch — fixes the known signup validation bug
# ---------------------------------------------------------------------------

_STUB_PATCH_PATH = "app.py"

_STUB_PATCHED_APP = textwrap.dedent('''\
    """
    Demo Target — Messy Python Flask Web App
    =========================================
    This is the *target* repository that MA-SET agents will work on.
    It is intentionally imperfect:
      - Missing input validation on several routes
      - No error handling on the signup endpoint
      - A protected legacy billing module (agents MUST NOT edit it)
      - Inconsistent response formats

    MA-SET agents will receive tickets asking them to improve this app.
    """

    from flask import Flask, jsonify, request

    app = Flask(__name__)

    # In-memory store (no persistence — keeps the demo self-contained)
    _users: dict = {}      # email -> {password, name}
    _tasks: dict = {}      # task_id -> {title, done, owner}
    _task_counter: list = [0]


    # ---------------------------------------------------------------------------
    # Health
    # ---------------------------------------------------------------------------

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})


    # ---------------------------------------------------------------------------
    # Input validation helper (added by Developer agent — DEMO-001)
    # ---------------------------------------------------------------------------

    def validate_signup(data: dict) -> None:
        """Raise ValueError if required signup fields are missing."""
        for field_name in ("email", "password"):
            if not data.get(field_name):
                raise ValueError(f"{field_name} required")


    # ---------------------------------------------------------------------------
    # Users
    # ---------------------------------------------------------------------------

    @app.route("/signup", methods=["POST"])
    def signup():
        data = request.json or {}
        try:
            validate_signup(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        email = data["email"]
        password = data["password"]
        name = data.get("name", "")

        if email in _users:
            return jsonify({"error": "user already exists"}), 409

        _users[email] = {"password": password, "name": name}
        return jsonify({"message": "created", "email": email}), 201


    @app.route("/login", methods=["POST"])
    def login():
        data = request.json or {}
        email = data.get("email")
        password = data.get("password")

        user = _users.get(email)
        if not user or user["password"] != password:
            return jsonify({"error": "invalid credentials"}), 401

        # Calls the protected billing module to activate the free trial
        from demo_target import legacy_billing
        legacy_billing.activate_trial(email)

        return jsonify({"message": "logged in", "email": email})


    # ---------------------------------------------------------------------------
    # Tasks — some validation present, some missing
    # ---------------------------------------------------------------------------

    @app.route("/tasks", methods=["GET"])
    def list_tasks():
        return jsonify(list(_tasks.values()))


    @app.route("/tasks", methods=["POST"])
    def create_task():
        data = request.json or {}
        title = data.get("title")
        if not title:
            return jsonify({"error": "title required"}), 400

        _task_counter[0] += 1
        task_id = _task_counter[0]
        _tasks[task_id] = {"id": task_id, "title": title, "done": False, "owner": data.get("owner", "")}
        return jsonify(_tasks[task_id]), 201


    @app.route("/tasks/<int:task_id>", methods=["PATCH"])
    def update_task(task_id):
        task = _tasks.get(task_id)
        if not task:
            return jsonify({"error": "not found"}), 404

        data = request.json or {}
        if "done" in data:
            task["done"] = bool(data["done"])
        if "title" in data:
            task["title"] = data["title"]

        return jsonify(task)


    @app.route("/tasks/<int:task_id>", methods=["DELETE"])
    def delete_task(task_id):
        if task_id not in _tasks:
            return jsonify({"error": "not found"}), 404
        del _tasks[task_id]
        return jsonify({"message": "deleted"})


    # ---------------------------------------------------------------------------
    # Utility — clears in-memory state (test helper)
    # ---------------------------------------------------------------------------

    def _reset():
        _users.clear()
        _tasks.clear()
        _task_counter[0] = 0


    if __name__ == "__main__":
        app.run(debug=True, port=5050)
''')


# ---------------------------------------------------------------------------
# Developer Agent
# ---------------------------------------------------------------------------

class DeveloperAgent:
    """
    Implements the changes described in a design spec.

    Parameters
    ----------
    adapter : ModelAdapter
        The LLM adapter (can be stub, Gemini, or Groq).
    path_filter : PathFilter
        Enforces which files may be written.
    project_root : Path
        Root of the project; file paths in the design spec are relative here.
    event_callback : callable, optional
        Receives event dicts for every significant action.
    node : str
        IDEF0 node tag (always "A3" for Developer).
    """

    SYSTEM_PROMPT = textwrap.dedent("""\
        You are the Developer agent in the MA-SET pipeline.
        You receive a design spec and must produce a Python code patch.
        Rules:
        - Only edit files listed in the design spec under 'Files to modify'.
        - Do NOT touch protected files (deny list).
        - Output ONLY a unified diff (--- a/... +++ b/... @@...) with no commentary.
        - The diff must be directly applicable with `patch -p1`.
    """)

    def __init__(
        self,
        adapter: ModelAdapter,
        path_filter: PathFilter,
        project_root: Path = Path("."),
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A3",
        agent: str = "developer",
    ):
        self._adapter = adapter
        self._pf = path_filter
        self._root = project_root.resolve()
        self._cb = event_callback
        self._node = node
        self._agent = agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        design_spec: str,
        run_id: str,
        defect_list: Optional[List[str]] = None,
        retry_number: int = 0,
    ) -> DeveloperResult:
        """
        Generate and apply code changes for the given *design_spec*.

        Parameters
        ----------
        design_spec : str
            Output from the Architect agent describing what to change and where.
        run_id : str
            Current pipeline run ID (for event correlation).
        defect_list : list[str], optional
            Defects from the Tester — injected on retry so the LLM can fix them.
        retry_number : int
            0 = first attempt; >0 = retry after defects.
        """
        self._emit(run_id, "agent_started", {
            "retry": retry_number,
            "has_defects": bool(defect_list),
        })

        try:
            result = self._implement(design_spec, run_id, defect_list, retry_number)
        except Exception as exc:
            self._emit(run_id, "agent_escalated", {"error": str(exc)})
            return DeveloperResult(
                success=False, diff="", files_changed=[], patched_contents={},
                error=str(exc),
            )

        self._emit(run_id, "agent_finished", {
            "files_changed": result.files_changed,
            "diff_lines": result.diff.count("\n"),
        })
        return result

    implement = run

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _implement(
        self,
        design_spec: str,
        run_id: str,
        defect_list: Optional[List[str]],
        retry_number: int,
    ) -> DeveloperResult:
        from ma_set.model.adapter import Provider

        if self._adapter.config.provider == Provider.STUB:
            return self._stub_implement(run_id)
        return self._llm_implement(design_spec, run_id, defect_list, retry_number)

    # -- Stub path --

    def _stub_implement(self, run_id: str) -> DeveloperResult:
        """Apply the pre-written patch that fixes signup validation."""
        target_path = "demo_target/app.py"

        # Call the adapter (even in stub mode) so llm_stub_response event fires
        self._adapter.complete(
            "Implement the diff for signup validation",
            node=self._node,
            agent=self._agent,
            run_id=run_id,
            system_prompt=self.SYSTEM_PROMPT,
        )

        # Read original through PathFilter (always allowed for reads)
        self._emit(run_id, "tool_call", {"action": "read", "path": target_path})
        original = (self._root / target_path).read_text(encoding="utf-8")
        self._emit(run_id, "tool_result", {"bytes": len(original)})

        # Write patched content through PathFilter
        self._emit(run_id, "tool_call", {"action": "write", "path": target_path})
        diff = self._pf.write_patch(target_path, original, _STUB_PATCHED_APP)
        if not diff.strip():
            diff = (
                "--- a/demo_target/app.py\n"
                "+++ b/demo_target/app.py\n"
                "@@ -35,6 +35,12 @@\n"
                "+def validate_signup(data: dict) -> None:\n"
                "+    for field_name in ('email', 'password'):\n"
                "+        if not data.get(field_name):\n"
                "+            raise ValueError(f'{field_name} required')\n"
            )
        self._emit(run_id, "tool_result", {"diff_lines": diff.count("\n")})

        self._emit(run_id, "diff_produced", {
            "files": [target_path],
            "diff_snippet": diff[:300],
        })

        return DeveloperResult(
            success=True,
            diff=diff,
            files_changed=[target_path],
            patched_contents={target_path: _STUB_PATCHED_APP},
        )

    # -- Real LLM path --

    def _llm_implement(
        self,
        design_spec: str,
        run_id: str,
        defect_list: Optional[List[str]],
        retry_number: int,
    ) -> DeveloperResult:
        """Call the real LLM to generate a patch."""
        prompt_parts = [
            f"Design spec:\n{design_spec}",
        ]
        if defect_list:
            prompt_parts.append(
                "Previous attempt failed with these defects:\n"
                + "\n".join(f"  - {d}" for d in defect_list)
                + "\nFix all defects in your patch."
            )
        prompt = "\n\n".join(prompt_parts)

        raw_diff = self._adapter.complete(
            prompt,
            node=self._node,
            agent=self._agent,
            run_id=run_id,
            system_prompt=self.SYSTEM_PROMPT,
        )

        # Extract and apply each changed file from the diff
        changed, patched = self._apply_diff(raw_diff, run_id)

        self._emit(run_id, "diff_produced", {
            "files": changed,
            "diff_snippet": raw_diff[:300],
        })

        return DeveloperResult(
            success=True,
            diff=raw_diff,
            files_changed=changed,
            patched_contents=patched,
        )

    def _apply_diff(
        self, raw_diff: str, run_id: str
    ) -> tuple[list, dict]:
        """
        Parse a unified diff and apply each hunk.
        Returns (files_changed, {path: new_content}).
        This is a best-effort parser for LLM-generated diffs.
        """
        import re

        changed: List[str] = []
        patched: Dict[str, str] = {}
        current_path: Optional[str] = None
        current_lines: List[str] = []

        for line in raw_diff.splitlines(keepends=True):
            m = re.match(r'^\+\+\+ b/(.+)', line)
            if m:
                if current_path and current_lines:
                    self._write_lines(current_path, current_lines, run_id,
                                      changed, patched)
                current_path = m.group(1).strip()
                current_lines = []
                continue
            if line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("+"):
                current_lines.append(line[1:])
            elif line.startswith(" "):
                current_lines.append(line[1:])
            # Lines starting with '-' are removed — skip

        if current_path and current_lines:
            self._write_lines(current_path, current_lines, run_id, changed, patched)

        return changed, patched

    def _write_lines(self, path, lines, run_id, changed, patched):
        content = "".join(lines)
        original = ""
        full = self._root / path
        if full.exists():
            original = full.read_text(encoding="utf-8")
        self._pf.write_patch(path, original, content)
        changed.append(path)
        patched[path] = content

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _emit(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        if self._cb:
            try:
                self._cb({
                    "run_id": run_id,
                    "node": self._node,
                    "agent": self._agent,
                    "event_type": event_type,
                    "payload": payload,
                })
            except Exception:
                pass
