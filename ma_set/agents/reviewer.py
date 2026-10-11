"""
P2.5 — Reviewer Agent
=======================
Reviews a code diff against the design spec and coding standards, then
produces a structured ReviewVerdict.

The Reviewer is the quality gate between the Developer (A3) and DevOps (A5).
If it rejects the diff, the FB2 loop sends the design flaws back to the
Architect (A2); if it rejects on implementation grounds, the FB1 loop
sends defects to the Developer (A3).

Checks performed
----------------
Spec adherence   — do the changed files match those listed in the spec?
Protected files  — does the diff touch any protected files?
Acceptance crit  — does the diff implement all acceptance criteria
                   (checked heuristically in stub mode; by LLM in real mode)?
Style            — ruff lint output (from TesterResult) passes review?

Events emitted
--------------
  AGENT_STARTED
  REVIEW_VERDICT
  AGENT_FINISHED
  AGENT_ESCALATED
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ma_set.agents.architect import DesignSpec
from ma_set.agents.developer import DeveloperResult
from ma_set.agents.tester import TesterResult
from ma_set.model.adapter import ModelAdapter


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReviewVerdict:
    approved: bool
    verdict: str                   # "APPROVED" | "REJECTED"
    reasons: List[str]             # Reasons for rejection (empty if approved)
    design_flaws: List[str]        # Flaws in the spec itself → triggers FB2
    implementation_defects: List[str]  # Code bugs → triggers FB1
    raw_llm_output: str = ""

    @property
    def feedback_for_architect(self) -> List[str]:
        return self.design_flaws or self.reasons

    def render(self) -> str:
        lines = [f"=== REVIEW VERDICT: {self.verdict} ==="]
        if self.reasons:
            lines.append("Reasons:")
            for r in self.reasons:
                lines.append(f"  [FAIL]  {r}")
        if self.design_flaws:
            lines.append("\nDesign flaws (-> Architect):")
            for f in self.design_flaws:
                lines.append(f"  [FLAW]  {f}")
        if self.implementation_defects:
            lines.append("\nImplementation defects (-> Developer):")
            for d in self.implementation_defects:
                lines.append(f"  [DEFECT]  {d}")
        if self.approved:
            lines.append("\n[APPROVED]  Diff approved — ready for DevOps delivery.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reviewer Agent
# ---------------------------------------------------------------------------

class ReviewerAgent:
    """
    Reviews a diff against the design spec and test results.

    Parameters
    ----------
    adapter : ModelAdapter
    deny_list : list[str]
        Protected file paths (from Config).
    event_callback : callable, optional
    node : str
        Always "A4".
    """

    SYSTEM_PROMPT = textwrap.dedent("""\
        You are the Reviewer agent in the MA-SET pipeline.
        You receive a design spec, a code diff, and test results.
        Review the diff for:
          1. Spec adherence — does the diff match the design spec?
          2. Protected file safety — does the diff touch any protected files?
          3. Acceptance criteria — does the diff implement all criteria?
          4. Code quality — obvious bugs, missing error handling?
        Respond with:
          VERDICT: APPROVED or REJECTED
          REASONS: bullet list of reasons for rejection (empty if APPROVED)
          DESIGN_FLAWS: bullet list of flaws in the spec itself (→ Architect)
          IMPLEMENTATION_DEFECTS: bullet list of code bugs (→ Developer)
    """)

    def __init__(
        self,
        adapter: ModelAdapter,
        deny_list: Optional[List[str]] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        node: str = "A4",
        agent: str = "reviewer",
    ):
        self._adapter = adapter
        self._deny = deny_list or []
        self._cb = event_callback
        self._node = node
        self._agent = agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        design_spec: DesignSpec,
        developer_result: DeveloperResult,
        tester_result: TesterResult,
        run_id: str,
    ) -> ReviewVerdict:
        """
        Produce a ReviewVerdict.

        Parameters
        ----------
        design_spec : DesignSpec
            From the Architect agent.
        developer_result : DeveloperResult
            From the Developer agent — contains the diff.
        tester_result : TesterResult
            From the Tester agent — contains test pass/fail state.
        run_id : str
        """
        self._emit(run_id, "agent_started", {
            "diff_lines": developer_result.diff.count("\n"),
            "tests_passed": tester_result.tests_passed,
            "tests_failed": tester_result.tests_failed,
        })

        try:
            verdict = self._review(design_spec, developer_result, tester_result, run_id)
        except Exception as exc:
            self._emit(run_id, "agent_escalated", {"error": str(exc)})
            raise

        self._emit(run_id, "review_verdict", {
            "verdict": verdict.verdict,
            "design_flaws": len(verdict.design_flaws),
            "implementation_defects": len(verdict.implementation_defects),
            "approved": verdict.approved,
        })
        self._emit(run_id, "agent_finished", {"approved": verdict.approved})
        return verdict

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _review(
        self,
        spec: DesignSpec,
        dev: DeveloperResult,
        test: TesterResult,
        run_id: str,
    ) -> ReviewVerdict:
        from ma_set.model.adapter import Provider
        if self._adapter.config.provider == Provider.STUB:
            return self._stub_review(spec, dev, test)
        return self._llm_review(spec, dev, test, run_id)

    # -- Stub path --

    def _stub_review(
        self, spec: DesignSpec, dev: DeveloperResult, test: TesterResult
    ) -> ReviewVerdict:
        reasons: List[str] = []
        design_flaws: List[str] = []
        impl_defects: List[str] = []

        # Check 1: tests must pass
        if not test.success:
            impl_defects.extend(test.defect_list[:5])
            reasons.append(f"Tests failing: {test.tests_failed} failed.")

        # Check 2: no protected files in diff
        protected_touched = [
            f for f in dev.files_changed
            if any(
                (d.endswith("/") and f.startswith(d.rstrip("/"))) or f == d
                for d in self._deny
            )
        ]
        if protected_touched:
            design_flaws.append(
                f"Diff touches protected files: {protected_touched}. "
                "Design spec must not allow this."
            )
            reasons.append(f"Protected files modified: {protected_touched}")

        # Check 3: files changed match spec
        unexpected = [
            f for f in dev.files_changed
            if f not in spec.files_to_modify
        ]
        if unexpected:
            impl_defects.append(
                f"Diff modifies files not in design spec: {unexpected}"
            )
            reasons.append(f"Unexpected files changed: {unexpected}")

        # Check 4: diff is non-empty
        if not dev.diff.strip():
            impl_defects.append("Diff is empty — no changes produced.")
            reasons.append("Empty diff.")

        # Check 5 (stub-specific): validate_signup in patched content
        app_content = dev.patched_contents.get("demo_target/app.py", "")
        if app_content and "validate_signup" not in app_content:
            impl_defects.append(
                "validate_signup helper not found in patched app.py"
            )
            reasons.append("Acceptance criteria not met: missing validate_signup.")

        approved = len(reasons) == 0
        return ReviewVerdict(
            approved=approved,
            verdict="APPROVED" if approved else "REJECTED",
            reasons=reasons,
            design_flaws=design_flaws,
            implementation_defects=impl_defects,
        )

    # -- Real LLM path --

    def _llm_review(
        self,
        spec: DesignSpec,
        dev: DeveloperResult,
        test: TesterResult,
        run_id: str,
    ) -> ReviewVerdict:
        prompt = "\n\n".join([
            f"Design spec:\n{spec.render()}",
            f"Code diff:\n{dev.diff[:3000]}",
            f"Test results: {test.tests_passed} passed, {test.tests_failed} failed.\n"
            f"Defects: {test.defect_list[:5]}",
            f"Lint errors: {test.lint_errors[:5]}",
        ])
        raw = self._adapter.complete(
            prompt, node=self._node, agent=self._agent,
            run_id=run_id, system_prompt=self.SYSTEM_PROMPT,
        )
        return self._parse_llm_verdict(raw)

    def _parse_llm_verdict(self, raw: str) -> ReviewVerdict:
        import re

        def _extract(label: str) -> str:
            m = re.search(rf'^{label}:\s*(.+?)(?=\n[A-Z_]+:|$)', raw, re.M | re.S)
            return m.group(1).strip() if m else ""

        verdict_str = _extract("VERDICT").upper()
        approved = "APPROVED" in verdict_str
        reasons = [
            l.lstrip("->•* ").strip()
            for l in _extract("REASONS").splitlines() if l.strip()
        ]
        design_flaws = [
            l.lstrip("->•* ").strip()
            for l in _extract("DESIGN_FLAWS").splitlines() if l.strip()
        ]
        impl_defects = [
            l.lstrip("->•* ").strip()
            for l in _extract("IMPLEMENTATION_DEFECTS").splitlines() if l.strip()
        ]
        return ReviewVerdict(
            approved=approved,
            verdict="APPROVED" if approved else "REJECTED",
            reasons=reasons,
            design_flaws=design_flaws,
            implementation_defects=impl_defects,
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
