"""
Phase 2 Tests — Architect, Impact Analysis, Gate, Reviewer, FB2 Loop (P2.1–P2.6)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ma_set.tools.code_index import CodeIndex, SearchResult, Symbol
from ma_set.agents.architect import ArchitectAgent, DesignSpec, ImpactReport
from ma_set.agents.gate import GateMode, HumanGate
from ma_set.agents.reviewer import ReviewerAgent, ReviewVerdict
from ma_set.agents.fb2_loop import ArchitectReviewerLoop, Phase2Result
from ma_set.agents.developer import DeveloperResult
from ma_set.agents.tester import TesterResult
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider
from ma_set.protection.path_filter import PathFilter
from ma_set.config import Config


# ============================================================
# Helpers (reused from Phase 1 tests)
# ============================================================

def _make_project(tmp: Path) -> Path:
    dt = tmp / "demo_target"
    dt.mkdir()
    (dt / "__init__.py").write_text("")
    real_app = Path("demo_target/app.py")
    (dt / "app.py").write_text(real_app.read_text())
    (dt / "legacy_billing.py").write_text(
        "# protected\n_TRIALS={}\n"
        "def activate_trial(e): _TRIALS[e]={'active':True}\n"
        "def get_trial_status(e): return _TRIALS.get(e,{})\n"
        "def cancel_trial(e):\n if e in _TRIALS: _TRIALS[e]['active']=False\n"
    )
    tests = dt / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_app.py").write_text(
        Path("demo_target/tests/test_app.py").read_text()
    )
    return tmp


def _stub_adapter(events: list) -> ModelAdapter:
    return ModelAdapter(ModelConfig(provider=Provider.STUB), event_callback=events.append)


def _make_filter(tmp: Path, events: list) -> PathFilter:
    return PathFilter(
        allow_list=["demo_target/app.py", "demo_target/tests/"],
        deny_list=["demo_target/legacy_billing.py", ".venv/", ".git/"],
        project_root=tmp,
        event_callback=events.append,
        run_id="test-run",
        node="A3",
        agent="developer",
    )


# ============================================================
# P2.1 — Code Index
# ============================================================

class TestCodeIndex:

    def test_search_finds_pattern(self):
        idx = CodeIndex(root=Path("demo_target"))
        results = idx.search("signup")
        assert any("signup" in r.snippet.lower() for r in results)

    def test_search_returns_file_and_line(self):
        idx = CodeIndex(root=Path("demo_target"))
        results = idx.search("def health")
        assert results
        r = results[0]
        assert r.file
        assert r.line > 0
        assert "health" in r.snippet.lower()

    def test_search_no_match_returns_empty(self):
        idx = CodeIndex(root=Path("demo_target"))
        results = idx.search("xyzzy_no_such_pattern_12345")
        assert results == []

    def test_symbols_finds_functions(self):
        idx = CodeIndex(root=Path("."))
        syms = idx.symbols("demo_target/app.py")
        names = [s.name for s in syms]
        assert "signup" in names
        assert "health" in names

    def test_symbols_finds_classes(self, tmp_path):
        (tmp_path / "mod.py").write_text(
            "class Foo:\n    def bar(self): pass\n"
        )
        idx = CodeIndex(root=tmp_path)
        syms = idx.symbols("mod.py")
        kinds = {s.kind for s in syms}
        names = {s.name for s in syms}
        assert "class" in kinds
        assert "Foo" in names
        assert "method" in kinds

    def test_symbols_invalid_file_returns_empty(self):
        idx = CodeIndex(root=Path("."))
        assert idx.symbols("non_existent_file.py") == []

    def test_references_finds_files(self):
        idx = CodeIndex(root=Path("."))
        refs = idx.references("signup")
        assert any("app.py" in r for r in refs)

    def test_list_files_excludes_venv(self):
        idx = CodeIndex(root=Path("."))
        files = idx.list_files("demo_target")
        assert not any(".venv" in f for f in files)

    def test_flag_protected_identifies_denied_paths(self):
        flagged = CodeIndex.flag_protected(
            changed=["demo_target/app.py", "demo_target/legacy_billing.py"],
            deny_list=["demo_target/legacy_billing.py"],
        )
        assert "demo_target/legacy_billing.py" in flagged
        assert "demo_target/app.py" not in flagged

    def test_flag_protected_empty_when_no_overlap(self):
        flagged = CodeIndex.flag_protected(
            changed=["demo_target/app.py"],
            deny_list=["demo_target/legacy_billing.py"],
        )
        assert flagged == []


# ============================================================
# P2.2 + P2.3 — Architect Agent & Impact Report
# ============================================================

class TestArchitectAgent:

    def test_stub_architect_produces_design_spec(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        idx = CodeIndex(root=tmp_path)
        arch = ArchitectAgent(
            adapter=adapter,
            code_index=idx,
            deny_list=Config.DENY_LIST,
            project_root=tmp_path,
            event_callback=events.append,
        )
        spec = arch.run(task_breakdown="Fix signup validation", run_id="t1")
        assert isinstance(spec, DesignSpec)
        assert spec.task_summary
        assert spec.files_to_modify

    def test_design_spec_identifies_protected_files(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        idx = CodeIndex(root=tmp_path)
        arch = ArchitectAgent(
            adapter=adapter, code_index=idx,
            deny_list=Config.DENY_LIST, project_root=tmp_path,
            event_callback=events.append,
        )
        spec = arch.run(task_breakdown="Fix signup", run_id="t1")
        assert "demo_target/legacy_billing.py" in spec.files_protected

    def test_impact_report_no_protected_files_touched(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        idx = CodeIndex(root=tmp_path)
        arch = ArchitectAgent(
            adapter=adapter, code_index=idx,
            deny_list=Config.DENY_LIST, project_root=tmp_path,
            event_callback=events.append,
        )
        spec = arch.run(task_breakdown="Fix signup", run_id="t1")
        # Stub design does NOT touch protected files
        assert not spec.impact_report.requires_human_signoff

    def test_architect_emits_all_key_events(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        idx = CodeIndex(root=tmp_path)
        arch = ArchitectAgent(
            adapter=adapter, code_index=idx,
            deny_list=Config.DENY_LIST, project_root=tmp_path,
            event_callback=events.append,
        )
        arch.run(task_breakdown="Fix signup", run_id="t1")
        types = {e["event_type"] for e in events}
        assert "agent_started" in types
        assert "impact_report" in types
        assert "design_spec" in types
        assert "agent_finished" in types

    def test_impact_report_render_contains_key_sections(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        idx = CodeIndex(root=tmp_path)
        arch = ArchitectAgent(
            adapter=adapter, code_index=idx,
            deny_list=Config.DENY_LIST, project_root=tmp_path,
            event_callback=events.append,
        )
        spec = arch.run(task_breakdown="Fix signup", run_id="t1")
        rendered = spec.impact_report.render()
        assert "IMPACT REPORT" in rendered
        assert "MODIFY" in rendered

    def test_design_spec_render_contains_acceptance_criteria(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        idx = CodeIndex(root=tmp_path)
        arch = ArchitectAgent(
            adapter=adapter, code_index=idx,
            deny_list=Config.DENY_LIST, project_root=tmp_path,
            event_callback=events.append,
        )
        spec = arch.run(task_breakdown="Fix signup", run_id="t1")
        assert spec.acceptance_criteria
        rendered = spec.render()
        assert "Acceptance criteria" in rendered


# ============================================================
# P2.4 — Human Sign-Off Gate
# ============================================================

class TestHumanGate:

    def test_auto_approve_always_approves(self):
        events = []
        gate = HumanGate(mode=GateMode.AUTO_APPROVE, event_callback=events.append)
        decision = gate.check("some design spec", run_id="t1")
        assert decision.approved is True

    def test_auto_reject_always_rejects(self):
        events = []
        gate = HumanGate(mode=GateMode.AUTO_REJECT, event_callback=events.append)
        decision = gate.check("some design spec", run_id="t1")
        assert decision.approved is False

    def test_gate_emits_opened_event(self):
        events = []
        gate = HumanGate(mode=GateMode.AUTO_APPROVE, event_callback=events.append)
        gate.check("spec", run_id="t1")
        types = [e["event_type"] for e in events]
        assert "human_gate_opened" in types

    def test_gate_emits_approved_event(self):
        events = []
        gate = HumanGate(mode=GateMode.AUTO_APPROVE, event_callback=events.append)
        gate.check("spec", run_id="t1")
        types = [e["event_type"] for e in events]
        assert "human_gate_approved" in types

    def test_gate_emits_rejected_event_on_auto_reject(self):
        events = []
        gate = HumanGate(mode=GateMode.AUTO_REJECT, event_callback=events.append)
        gate.check("spec", run_id="t1")
        types = [e["event_type"] for e in events]
        assert "human_gate_rejected" in types

    def test_gate_decision_has_elapsed_time(self):
        gate = HumanGate(mode=GateMode.AUTO_APPROVE)
        decision = gate.check("spec", run_id="t1")
        assert isinstance(decision.elapsed_s, float)

    def test_file_mode_auto_decision(self, tmp_path):
        import json, time, threading

        gate_dir = tmp_path / "gates"
        events = []
        gate = HumanGate(
            mode=GateMode.FILE,
            gate_dir=gate_dir,
            timeout_s=10,
            event_callback=events.append,
        )

        # Write the decision file slightly after the gate opens
        def _write_decision():
            time.sleep(0.5)
            decision_dir = gate_dir / "decisions"
            decision_dir.mkdir(parents=True, exist_ok=True)
            (decision_dir / "file-run.json").write_text(
                json.dumps({"decision": "approve", "comment": "LGTM"})
            )

        t = threading.Thread(target=_write_decision, daemon=True)
        t.start()
        decision = gate.check("spec", run_id="file-run")
        t.join(timeout=5)

        assert decision.approved is True
        assert "LGTM" in decision.comment


# ============================================================
# P2.5 — Reviewer Agent
# ============================================================

class TestReviewerAgent:

    def _good_dev_result(self) -> DeveloperResult:
        from ma_set.agents.developer import _STUB_PATCHED_APP
        return DeveloperResult(
            success=True,
            diff="--- a/demo_target/app.py\n+++ b/demo_target/app.py\n+def validate_signup",
            files_changed=["demo_target/app.py"],
            patched_contents={"demo_target/app.py": _STUB_PATCHED_APP},
        )

    def _good_test_result(self) -> TesterResult:
        return TesterResult(
            success=True, tests_total=22, tests_passed=22,
            tests_failed=0, tests_xfailed=0,
            defect_list=[], lint_errors=[],
            raw_pytest_output="22 passed", raw_lint_output="",
        )

    def _bad_test_result(self) -> TesterResult:
        return TesterResult(
            success=False, tests_total=10, tests_passed=8,
            tests_failed=2, tests_xfailed=0,
            defect_list=["FAILED test_signup_missing_email_returns_400"],
            lint_errors=[],
            raw_pytest_output="2 failed", raw_lint_output="",
        )

    def _stub_spec(self) -> DesignSpec:
        from ma_set.agents.architect import _STUB_DESIGN
        return _STUB_DESIGN

    def test_stub_reviewer_approves_good_diff(self):
        events = []
        adapter = _stub_adapter(events)
        reviewer = ReviewerAgent(
            adapter=adapter,
            deny_list=Config.DENY_LIST,
            event_callback=events.append,
        )
        verdict = reviewer.run(
            design_spec=self._stub_spec(),
            developer_result=self._good_dev_result(),
            tester_result=self._good_test_result(),
            run_id="t1",
        )
        assert verdict.approved is True
        assert verdict.verdict == "APPROVED"

    def test_stub_reviewer_rejects_failing_tests(self):
        events = []
        adapter = _stub_adapter(events)
        reviewer = ReviewerAgent(
            adapter=adapter,
            deny_list=Config.DENY_LIST,
            event_callback=events.append,
        )
        verdict = reviewer.run(
            design_spec=self._stub_spec(),
            developer_result=self._good_dev_result(),
            tester_result=self._bad_test_result(),
            run_id="t1",
        )
        assert verdict.approved is False
        assert verdict.implementation_defects

    def test_stub_reviewer_rejects_protected_file_touch(self):
        events = []
        adapter = _stub_adapter(events)
        reviewer = ReviewerAgent(
            adapter=adapter,
            deny_list=["demo_target/legacy_billing.py"],
            event_callback=events.append,
        )
        # Developer changed a protected file
        bad_dev = DeveloperResult(
            success=True,
            diff="--- a/demo_target/legacy_billing.py\n+++ ...",
            files_changed=["demo_target/legacy_billing.py"],
            patched_contents={"demo_target/legacy_billing.py": "# hacked"},
        )
        verdict = reviewer.run(
            design_spec=self._stub_spec(),
            developer_result=bad_dev,
            tester_result=self._good_test_result(),
            run_id="t1",
        )
        assert verdict.approved is False
        assert verdict.design_flaws

    def test_reviewer_emits_review_verdict_event(self):
        events = []
        adapter = _stub_adapter(events)
        reviewer = ReviewerAgent(
            adapter=adapter, deny_list=Config.DENY_LIST, event_callback=events.append,
        )
        reviewer.run(
            design_spec=self._stub_spec(),
            developer_result=self._good_dev_result(),
            tester_result=self._good_test_result(),
            run_id="t1",
        )
        assert any(e["event_type"] == "review_verdict" for e in events)

    def test_verdict_render_shows_approved(self):
        events = []
        adapter = _stub_adapter(events)
        reviewer = ReviewerAgent(
            adapter=adapter, deny_list=Config.DENY_LIST, event_callback=events.append,
        )
        verdict = reviewer.run(
            design_spec=self._stub_spec(),
            developer_result=self._good_dev_result(),
            tester_result=self._good_test_result(),
            run_id="t1",
        )
        assert "APPROVED" in verdict.render()


# ============================================================
# P2.6 — Architect ↔ Reviewer Loop (FB2)
# ============================================================

class TestArchitectReviewerLoop:

    def test_full_phase2_stub_succeeds(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        idx = CodeIndex(root=tmp_path)
        loop = ArchitectReviewerLoop(
            adapter=adapter,
            path_filter=pf,
            code_index=idx,
            project_root=tmp_path,
            task_breakdown="Fix signup validation",
            gate_mode=GateMode.AUTO_APPROVE,
            test_path="demo_target/tests",
            src_path="demo_target/app.py",
            max_retries=3,
            event_callback=events.append,
        )
        result = loop.run()
        assert result.success is True
        assert result.design_iterations == 1
        assert result.final_review_verdict.approved is True

    def test_phase2_escalates_when_gate_always_rejects(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        idx = CodeIndex(root=tmp_path)
        loop = ArchitectReviewerLoop(
            adapter=adapter, path_filter=pf, code_index=idx,
            project_root=tmp_path,
            task_breakdown="Fix signup",
            gate_mode=GateMode.AUTO_REJECT,
            max_retries=2,
            event_callback=events.append,
        )
        result = loop.run()
        assert result.success is False
        assert result.escalation_report
        assert any(e["event_type"] == "run_escalated" for e in events)

    def test_phase2_emits_all_required_events(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        idx = CodeIndex(root=tmp_path)
        loop = ArchitectReviewerLoop(
            adapter=adapter, path_filter=pf, code_index=idx,
            project_root=tmp_path,
            task_breakdown="Fix signup",
            gate_mode=GateMode.AUTO_APPROVE,
            max_retries=3,
            event_callback=events.append,
        )
        loop.run()
        types = {e["event_type"] for e in events}
        required = {
            "run_started", "agent_started",  # architect
            "impact_report", "design_spec",  # architect outputs
            "human_gate_opened", "human_gate_approved",  # gate
            "diff_produced",                 # developer
            "test_results",                  # tester
            "review_verdict",                # reviewer
            "run_finished",
        }
        missing = required - types
        assert not missing, f"Missing event types: {missing}"

    def test_phase2_result_has_design_spec(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        idx = CodeIndex(root=tmp_path)
        loop = ArchitectReviewerLoop(
            adapter=adapter, path_filter=pf, code_index=idx,
            project_root=tmp_path, task_breakdown="Fix signup",
            gate_mode=GateMode.AUTO_APPROVE, max_retries=3,
            event_callback=events.append,
        )
        result = loop.run()
        assert result.design_spec is not None
        assert result.design_spec.task_summary
