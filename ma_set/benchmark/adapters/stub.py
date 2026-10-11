"""
Stub Agent Adapter
==================
Deterministic, offline agent adapter for unit testing and fast evaluation.
Can be configured to simulate clean passes, syntax errors, protected file attacks,
or tool loops.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ma_set.benchmark.adapters.base import AgentAdapter, AgentRunResult
from ma_set.benchmark.environments.isolated_env import IsolatedEnvironment
from ma_set.tools.ticket_intake import Ticket


class StubAgentAdapter(AgentAdapter):
    """
    Deterministic Agent Adapter that executes pre-configured behaviors.
    """

    def __init__(
        self,
        name: str = "stub_agent",
        version: str = "1.0.0",
        behavior: str = "pass",  # "pass", "fail", "trap_attack", "loop"
    ):
        super().__init__(name=name, version=version)
        self.behavior = behavior

    def run(
        self,
        task: Ticket | Any,
        environment: IsolatedEnvironment,
        config: Optional[Dict[str, Any]] = None,
    ) -> AgentRunResult:
        start_t = time.monotonic()
        cfg = config or {}
        behavior = cfg.get("behavior", self.behavior)

        meta = getattr(task, "metadata", {})
        meta_dict = meta.model_dump() if hasattr(meta, "model_dump") else (meta if isinstance(meta, dict) else {})
        is_trap = meta_dict.get("is_trap", False) or getattr(task, "task_type", "") in ("adversarial", "trap") or getattr(task, "id", "") in ("BENCH-006", "BENCH-027", "BENCH-028")

        # 1. Behavior: Trap Attack (attempts writing to protected files)
        if behavior == "trap_attack" or is_trap:

            target_path = "demo_target/legacy_billing.py"
            try:
                environment.write_file(target_path, "# malicious edit\n")
            except PermissionError as exc:
                return AgentRunResult(
                    agent_name=self.name,
                    agent_version=self.version,
                    success=False,
                    output="Write blocked by protection layer",
                    commands_executed=len(environment.commands_executed),
                    duration_s=time.monotonic() - start_t,
                    escalation_reason=str(exc),
                )

        # 2. Behavior: Fail
        if behavior == "fail":
            environment.execute("pytest demo_target/tests/ -v")
            return AgentRunResult(
                agent_name=self.name,
                agent_version=self.version,
                success=False,
                output="Agent gave up on task",
                commands_executed=len(environment.commands_executed),
                duration_s=time.monotonic() - start_t,
                escalation_reason="Tests failed to pass",
            )

        # 3. Behavior: Pass (apply patch and verify pytest)
        # Apply clean patch to demo_target/app.py
        target_path = "demo_target/app.py"
        if environment.file_exists(target_path):
            curr_code = (environment.work_dir / target_path).read_text(encoding="utf-8")
            task_desc = getattr(task, "prompt", getattr(task, "description", ""))
            task_title = getattr(task, "title", "").lower()

            if "def validate_signup" not in curr_code and ("validate_signup" in task_desc or "validation" in task_title or "signup" in task_title):
                patched_code = curr_code.replace(
                    "@app.route(\"/signup\", methods=[\"POST\"])\ndef signup():\n    data = request.json or {}\n",
                    "@app.route(\"/signup\", methods=[\"POST\"])\ndef signup():\n    data = request.json or {}\n    if not data.get(\"email\") or not data.get(\"password\"):\n        return jsonify({\"error\": \"missing required fields\"}), 400\n"
                )

                try:
                    environment.write_file(target_path, patched_code)
                except Exception:
                    pass

        # Execute tests in environment
        test_res = environment.execute(".venv/bin/python -m pytest demo_target/tests/ -v || pytest demo_target/tests/ -v")
        diff = environment.get_diff()

        return AgentRunResult(
            agent_name=self.name,
            agent_version=self.version,
            success=True,
            output="Task completed successfully.",
            diff=diff,
            files_modified=environment.files_modified,
            commands_executed=len(environment.commands_executed),
            llm_calls=2,
            cost_usd=0.0004,
            duration_s=time.monotonic() - start_t,
        )
