"""
P2.2 + P2.3 — Architect Agent & Impact Report Generator
=========================================================
The Architect agent receives a task breakdown from the Planner and produces:

  1. A **Design Spec** — what to change, how, and why.
  2. An **Impact Report** — which files are touched; protected files flagged.

The design spec is the primary input for the Developer agent (A3).
The impact report drives the human sign-off gate (P2.4).

In **stub mode** the agent produces a canned but realistic design spec that
describes fixing the signup validation bug in demo_target/app.py and flags
demo_target/legacy_billing.py as a protected file that must NOT be touched.

In **real LLM mode** the agent:
  1. Runs the code index to find relevant symbols and references.
  2. Sends a structured prompt with the task breakdown + index results.
  3. Parses the LLM response into a DesignSpec + ImpactReport.

Events emitted (P1.6 / P2)
---------------------------
  AGENT_STARTED
  TOOL_CALL / TOOL_RESULT  (for each index query)
  IMPACT_REPORT
  DESIGN_SPEC
  AGENT_FINISHED
  AGENT_ESCALATED
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.model.adapter import ModelAdapter
from ma_set.tools.code_index import CodeIndex


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ImpactReport:
    """P2.3 — Lists every file the change touches and flags protected ones."""
    files_to_modify: List[str]
    files_to_read: List[str]
    protected_files_touched: List[str]    # Non-empty = human sign-off required
    symbols_changed: List[str]
    summary: str

    @property
    def requires_human_signoff(self) -> bool:
        return bool(self.protected_files_touched)

    def render(self) -> str:
        lines = ["=== IMPACT REPORT ===", self.summary, ""]
        lines.append("Files to MODIFY:")
        for f in self.files_to_modify:
            lines.append(f"  [EDIT]  {f}")
        lines.append("\nFiles to READ (context only):")
        for f in self.files_to_read:
            lines.append(f"  [READ]  {f}")
        if self.protected_files_touched:
            lines.append("\n[WARNING] PROTECTED FILES TOUCHED — human sign-off required:")
            for f in self.protected_files_touched:
                lines.append(f"  [LOCKED]  {f}")
        else:
            lines.append("\n[OK] No protected files touched.")
        if self.symbols_changed:
            lines.append("\nSymbols changed:")
            for s in self.symbols_changed:
                lines.append(f"  ~  {s}")
        return "\n".join(lines)


@dataclass
class DesignSpec:
    """Full output of the Architect agent."""
    task_summary: str
    approach: str
    files_to_modify: List[str]
    files_protected: List[str]
    acceptance_criteria: List[str]
    impact_report: ImpactReport
    raw_llm_output: str = ""

    def render(self) -> str:
        lines = [
            "=== DESIGN SPEC ===",
            f"Task: {self.task_summary}",
            "",
            "Approach:",
            textwrap.indent(self.approach, "  "),
            "",
            "Files to modify:",
        ]
        for f in self.files_to_modify:
            lines.append(f"  [EDIT]    {f}  (ALLOWED)")
        for f in self.files_protected:
            lines.append(f"  [LOCKED]  {f}  (PROTECTED — DO NOT TOUCH)")
        lines.append("")
        lines.append("Acceptance criteria:")
        for ac in self.acceptance_criteria:
            lines.append(f"  [OK]  {ac}")
        lines.append("")
        lines.append(self.impact_report.render())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stub canned outputs
# ---------------------------------------------------------------------------

_STUB_DESIGN = DesignSpec(
    task_summary="DEMO-001: Add input validation to the /signup endpoint",
    approach=(
        "Add a validate_signup(data) helper in demo_target/app.py that raises "
        "ValueError when 'email' or 'password' is missing. "
        "Wrap the signup() route handler with a try/except that returns HTTP 400. "
        "Do NOT touch demo_target/legacy_billing.py."
    ),
    files_to_modify=["demo_target/app.py"],
    files_protected=["demo_target/legacy_billing.py"],
    acceptance_criteria=[
        "POST /signup with missing email returns 400 {'error': 'email required'}",
        "POST /signup with missing password returns 400 {'error': 'password required'}",
        "POST /signup with empty body returns 400",
        "POST /signup with valid payload still returns 201",
        "legacy_billing.py is not modified",
    ],
    impact_report=ImpactReport(
        files_to_modify=["demo_target/app.py"],
        files_to_read=["demo_target/legacy_billing.py"],
        protected_files_touched=[],
        symbols_changed=["signup", "validate_signup (new)"],
        summary="1 file modified (app.py). 1 protected file read but not touched.",
    ),
)


# ---------------------------------------------------------------------------
# Architect Agent
# ---------------------------------------------------------------------------

class ArchitectAgent:
    """
    Analyzes the codebase and produces a DesignSpec + ImpactReport.

    Parameters
    ----------
    adapter : ModelAdapter
    code_index : CodeIndex
    deny_list : list[str]
        Files that must never be modified (from Config).
    project_root : Path
    event_callback : callable, optional
    node : str
        Always "A2".
    """

    SYSTEM_PROMPT = textwrap.dedent("""\
        You are the Architect agent in the MA-SET pipeline.
        Given a task breakdown and relevant code snippets, produce a structured design spec.
        Your response MUST contain these labelled sections:
          TASK: <one-line summary>
          APPROACH: <paragraph describing the change>
          FILES_TO_MODIFY: <comma-separated list of relative file paths>
          FILES_PROTECTED: <comma-separated list of protected files that must not be changed>
          ACCEPTANCE_CRITERIA: <bullet list, one per line starting with ->
        Keep it concise. Mention protected files even if you will not touch them.
    """)

    def __init__(
        self,
        adapter: ModelAdapter,
        code_index: CodeIndex,
        deny_list: Optional[List[str]] = None,
        project_root: Path = Path("."),
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A2",
        agent: str = "architect",
    ):
        self._adapter = adapter
        self._index = code_index
        self._deny = deny_list or []
        self._root = project_root.resolve()
        self._cb = event_callback
        self._node = node
        self._agent = agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        task_breakdown: str,
        run_id: str,
        design_feedback: Optional[List[str]] = None,
        retry_number: int = 0,
    ) -> DesignSpec:
        """
        Produce a DesignSpec for *task_breakdown*.

        Parameters
        ----------
        task_breakdown : str
            Output from the Planner agent (A1).
        run_id : str
        design_feedback : list[str], optional
            Reviewer feedback injected on FB2 retry.
        retry_number : int
        """
        self._emit(run_id, "agent_started", {
            "retry": retry_number,
            "has_feedback": bool(design_feedback),
        })

        try:
            spec = self._design(task_breakdown, run_id, design_feedback, retry_number)
        except Exception as exc:
            self._emit(run_id, "agent_escalated", {"error": str(exc)})
            raise

        # Emit impact report + design spec events
        self._emit(run_id, "impact_report", {
            "files_to_modify": spec.impact_report.files_to_modify,
            "protected_touched": spec.impact_report.protected_files_touched,
            "requires_signoff": spec.impact_report.requires_human_signoff,
        })
        self._emit(run_id, "design_spec", {
            "task": spec.task_summary,
            "files_to_modify": spec.files_to_modify,
            "files_protected": spec.files_protected,
            "acceptance_criteria_count": len(spec.acceptance_criteria),
        })
        self._emit(run_id, "agent_finished", {
            "files_to_modify": spec.files_to_modify,
        })

        return spec

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _design(
        self,
        task_breakdown: str,
        run_id: str,
        design_feedback: Optional[List[str]],
        retry_number: int,
    ) -> DesignSpec:
        from ma_set.model.adapter import Provider
        if self._adapter.config.provider == Provider.STUB:
            return self._stub_design(run_id)
        return self._llm_design(task_breakdown, run_id, design_feedback, retry_number)

    # -- Stub path --

    def _stub_design(self, run_id: str) -> DesignSpec:
        """Return canned stub design + run index queries for event realism."""
        # Query the code index (so tool events are emitted)
        self._emit(run_id, "tool_call", {"action": "search", "pattern": "signup"})
        results = self._index.search("signup", max_results=10)
        self._emit(run_id, "tool_result", {"hits": len(results)})

        self._emit(run_id, "tool_call", {"action": "symbols", "file": "demo_target/app.py"})
        syms = self._index.symbols("demo_target/app.py")
        self._emit(run_id, "tool_result", {"symbols": [s.name for s in syms]})

        self._emit(run_id, "tool_call", {"action": "list_files"})
        files = self._index.list_files("demo_target")
        self._emit(run_id, "tool_result", {"files": files})

        return _STUB_DESIGN

    # -- Real LLM path --

    def _llm_design(
        self,
        task_breakdown: str,
        run_id: str,
        design_feedback: Optional[List[str]],
        retry_number: int,
    ) -> DesignSpec:
        # 1. Query the code index
        self._emit(run_id, "tool_call", {"action": "search", "pattern": task_breakdown[:40]})
        results = self._index.search(task_breakdown.split()[0], max_results=15)
        self._emit(run_id, "tool_result", {"hits": len(results)})

        self._emit(run_id, "tool_call", {"action": "list_files"})
        files = self._index.list_files()
        self._emit(run_id, "tool_result", {"files": files})

        # 2. Build prompt
        index_context = "\n".join(
            f"  {r.file}:{r.line}  {r.snippet}" for r in results[:10]
        )
        prompt_parts = [
            f"Task breakdown:\n{task_breakdown}",
            f"\nCode index results:\n{index_context}",
            f"\nProtected files (must never be modified):\n"
            + "\n".join(f"  {d}" for d in self._deny),
        ]
        if design_feedback:
            prompt_parts.append(
                "\nReviewer feedback on previous design:\n"
                + "\n".join(f"  - {fb}" for fb in design_feedback)
                + "\nRevise your design to address all feedback points."
            )
        prompt = "\n".join(prompt_parts)

        raw = self._adapter.complete(
            prompt, node=self._node, agent=self._agent,
            run_id=run_id, system_prompt=self.SYSTEM_PROMPT,
        )

        return self._parse_llm_output(raw, files)

    def _parse_llm_output(self, raw: str, all_files: List[str]) -> DesignSpec:
        """Parse the structured LLM response into a DesignSpec."""
        def _extract(label: str) -> str:
            import re
            m = re.search(rf'^{label}:\s*(.+?)(?=\n[A-Z_]+:|$)', raw, re.M | re.S)
            return m.group(1).strip() if m else ""

        task = _extract("TASK")
        approach = _extract("APPROACH")
        files_modify_raw = _extract("FILES_TO_MODIFY")
        files_protected_raw = _extract("FILES_PROTECTED")
        criteria_raw = _extract("ACCEPTANCE_CRITERIA")

        files_to_modify = [f.strip() for f in files_modify_raw.split(",") if f.strip()]
        files_protected = [f.strip() for f in files_protected_raw.split(",") if f.strip()]
        criteria = [
            line.lstrip("->• ").strip()
            for line in criteria_raw.splitlines()
            if line.strip()
        ]

        # P2.3: Impact report
        protected_touched = CodeIndex.flag_protected(files_to_modify, self._deny)
        impact = ImpactReport(
            files_to_modify=files_to_modify,
            files_to_read=[f for f in files_protected if f not in files_to_modify],
            protected_files_touched=protected_touched,
            symbols_changed=[],
            summary=f"{len(files_to_modify)} file(s) to modify. "
                    f"{len(protected_touched)} protected file(s) touched.",
        )

        return DesignSpec(
            task_summary=task,
            approach=approach,
            files_to_modify=files_to_modify,
            files_protected=files_protected,
            acceptance_criteria=criteria,
            impact_report=impact,
            raw_llm_output=raw,
        )

    # ------------------------------------------------------------------
    # Helpers
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
