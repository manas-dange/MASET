"""
Phase 1 Tests — Protection Layer + Agents (P1.1 – P1.6)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ma_set.protection.path_filter import PathFilter
from ma_set.protection.sandbox import Sandbox
from ma_set.agents.developer import DeveloperAgent
from ma_set.agents.tester import TesterAgent
from ma_set.agents.loop import DeveloperTesterLoop
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider


# ============================================================
# Helpers
# ============================================================

def _make_project(tmp: Path) -> Path:
    """Create a minimal demo_target tree inside tmp."""
    dt = tmp / "demo_target"
    dt.mkdir()
    (dt / "__init__.py").write_text("")
    # Copy the real app.py
    real_app = Path("demo_target/app.py")
    (dt / "app.py").write_text(real_app.read_text())
    # Protected file
    (dt / "legacy_billing.py").write_text("# protected\n_TRIALS={}\ndef activate_trial(e): _TRIALS[e]={'active':True}\ndef get_trial_status(e): return _TRIALS.get(e,{})\ndef cancel_trial(e):\n if e in _TRIALS: _TRIALS[e]['active']=False\n")
    # Tests
    tests_dir = dt / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    real_tests = Path("demo_target/tests/test_app.py")
    (tests_dir / "test_app.py").write_text(real_tests.read_text())
    return tmp


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


def _stub_adapter(events: list) -> ModelAdapter:
    return ModelAdapter(ModelConfig(provider=Provider.STUB), event_callback=events.append)


# ============================================================
# P1.1 — Path Filter
# ============================================================

class TestPathFilter:

    def test_allowed_path_passes(self, tmp_path):
        pf = _make_filter(tmp_path, [])
        allowed, reason = pf.check("demo_target/app.py")
        assert allowed is True
        assert "allow" in reason

    def test_denied_path_blocked(self, tmp_path):
        pf = _make_filter(tmp_path, [])
        allowed, reason = pf.check("demo_target/legacy_billing.py")
        assert allowed is False
        assert "deny" in reason

    def test_default_deny_unlisted_path(self, tmp_path):
        pf = _make_filter(tmp_path, [])
        allowed, _ = pf.check("demo_target/new_mystery_file.py")
        assert allowed is False

    def test_write_allowed_path_succeeds(self, tmp_path):
        _make_project(tmp_path)
        events = []
        pf = _make_filter(tmp_path, events)
        pf.write("demo_target/app.py", "# patched\n")
        assert (tmp_path / "demo_target" / "app.py").read_text() == "# patched\n"
        assert any(e["event_type"] == "file_write_allowed" for e in events)

    def test_write_denied_path_raises_and_logs(self, tmp_path):
        _make_project(tmp_path)
        events = []
        pf = _make_filter(tmp_path, events)
        with pytest.raises(PermissionError, match="blocked"):
            pf.write("demo_target/legacy_billing.py", "# hacked\n")
        # Protected file must be unchanged
        assert "hacked" not in (tmp_path / "demo_target" / "legacy_billing.py").read_text()
        # Event must be logged
        assert any(e["event_type"] == "file_write_blocked" for e in events)

    def test_dotdot_traversal_blocked(self, tmp_path):
        pf = _make_filter(tmp_path, [])
        allowed, _ = pf.check("../some_other_dir/secret.py")
        assert allowed is False

    def test_write_patch_returns_diff(self, tmp_path):
        _make_project(tmp_path)
        pf = _make_filter(tmp_path, [])
        diff = pf.write_patch("demo_target/app.py", "# old\n", "# new\n")
        assert "--- a/demo_target/app.py" in diff
        assert "+++ b/demo_target/app.py" in diff
        assert "-# old" in diff
        assert "+# new" in diff


# ============================================================
# P1.2 — Sandbox
# ============================================================

class TestSandbox:

    def test_sandbox_copies_source(self, tmp_path):
        _make_project(tmp_path)
        with Sandbox(source_dir=tmp_path, run_id="t1") as sb:
            assert (sb.work_dir / "demo_target" / "app.py").exists()

    def test_sandbox_is_discarded_after_exit(self, tmp_path):
        _make_project(tmp_path)
        with Sandbox(source_dir=tmp_path, run_id="t1") as sb:
            work = sb.work_dir
        assert not work.exists()

    def test_sandbox_runs_command(self, tmp_path):
        _make_project(tmp_path)
        with Sandbox(source_dir=tmp_path, run_id="t1") as sb:
            result = sb.run(["python", "-c", "print('hello')"])
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_sandbox_apply_patch(self, tmp_path):
        _make_project(tmp_path)
        with Sandbox(source_dir=tmp_path, run_id="t1") as sb:
            sb.apply_patch("demo_target/app.py", "# patched\n")
            content = sb.read_file("demo_target/app.py")
        assert content == "# patched\n"

    def test_sandbox_emits_events(self, tmp_path):
        _make_project(tmp_path)
        events = []
        with Sandbox(source_dir=tmp_path, run_id="t1", event_callback=events.append) as sb:
            sb.run(["python", "-c", "pass"])
        types = [e["event_type"] for e in events]
        assert "tool_call" in types
        assert "sandbox_command" in types
        assert "sandbox_result" in types


# ============================================================
# P1.3 — Developer Agent
# ============================================================

class TestDeveloperAgent:

    def test_stub_developer_succeeds(self, tmp_path):
        _make_project(tmp_path)
        events = []
        pf = _make_filter(tmp_path, events)
        adapter = _stub_adapter(events)
        dev = DeveloperAgent(adapter, pf, project_root=tmp_path, event_callback=events.append)
        result = dev.run(design_spec="[stub]", run_id="t1")
        assert result.success is True
        assert result.diff != ""
        assert "demo_target/app.py" in result.files_changed

    def test_stub_developer_applies_patch(self, tmp_path):
        _make_project(tmp_path)
        events = []
        pf = _make_filter(tmp_path, events)
        adapter = _stub_adapter(events)
        dev = DeveloperAgent(adapter, pf, project_root=tmp_path, event_callback=events.append)
        dev.run(design_spec="[stub]", run_id="t1")
        content = (tmp_path / "demo_target" / "app.py").read_text()
        assert "validate_signup" in content

    def test_developer_blocked_from_protected_file(self, tmp_path):
        _make_project(tmp_path)
        events = []
        pf = _make_filter(tmp_path, events)
        # Try to write to protected file directly
        with pytest.raises(PermissionError):
            pf.write("demo_target/legacy_billing.py", "# hacked")
        # Event must be logged
        assert any(e["event_type"] == "file_write_blocked" for e in events)

    def test_developer_emits_agent_events(self, tmp_path):
        _make_project(tmp_path)
        events = []
        pf = _make_filter(tmp_path, events)
        adapter = _stub_adapter(events)
        dev = DeveloperAgent(adapter, pf, project_root=tmp_path, event_callback=events.append)
        dev.run(design_spec="[stub]", run_id="t1")
        types = [e["event_type"] for e in events]
        assert "agent_started" in types
        assert "diff_produced" in types
        assert "agent_finished" in types


# ============================================================
# P1.4 — Tester Agent
# ============================================================

class TestTesterAgent:

    def test_tester_runs_on_unpatched_code_has_xfails(self, tmp_path):
        _make_project(tmp_path)
        events = []
        tester = TesterAgent(
            project_root=tmp_path,
            test_path="demo_target/tests",
            src_path="demo_target/app.py",
            run_lint=False,
            event_callback=events.append,
        )
        result = tester.run(run_id="t1", patched_files={})
        # Baseline: 10 tests pass, 0 fail (3 are xfail so exit=0)
        assert result.success is True   # xfails don't break the run
        assert result.tests_xfailed == 3

    def test_tester_emits_test_results_event(self, tmp_path):
        _make_project(tmp_path)
        events = []
        tester = TesterAgent(
            project_root=tmp_path,
            test_path="demo_target/tests",
            run_lint=False,
            event_callback=events.append,
        )
        tester.run(run_id="t1")
        assert any(e["event_type"] == "test_results" for e in events)

    def test_tester_reports_defects_on_broken_code(self, tmp_path):
        _make_project(tmp_path)
        events = []
        tester = TesterAgent(
            project_root=tmp_path,
            test_path="demo_target/tests",
            run_lint=False,
            event_callback=events.append,
        )
        # Inject broken code — removes _reset → ImportError in test collection
        broken = "from flask import Flask\napp = Flask(__name__)\n"
        result = tester.run(run_id="t1", patched_files={"demo_target/app.py": broken})
        assert result.success is False
        # Either tests fail or collection errors populate the defect_list
        assert result.defect_list or result.tests_failed > 0


# ============================================================
# P1.5 — Developer-Tester Loop (FB1)
# ============================================================

class TestDeveloperTesterLoop:

    def test_loop_succeeds_first_attempt_stub(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        loop = DeveloperTesterLoop(
            adapter=adapter,
            path_filter=pf,
            project_root=tmp_path,
            design_spec="[stub] fix signup validation",
            test_path="demo_target/tests",
            src_path="demo_target/app.py",
            max_retries=3,
            event_callback=events.append,
        )
        result = loop.run()
        assert result.success is True
        assert result.attempts == 1   # stub fixes on first try

    def test_loop_emits_run_started_and_run_finished(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        loop = DeveloperTesterLoop(
            adapter=adapter, path_filter=pf, project_root=tmp_path,
            design_spec="[stub]", max_retries=3, event_callback=events.append,
        )
        loop.run()
        types = [e["event_type"] for e in events]
        assert "run_started" in types
        assert "run_finished" in types

    def test_loop_escalates_after_max_retries(self, tmp_path):
        """Force failure by giving the developer a broken design that
        cannot be fixed and checking escalation."""
        _make_project(tmp_path)
        events = []

        # Adapter that always returns broken diff (not stub mode — use a
        # custom provider string that falls through to stub but we patch result)
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)

        # Monkeypatch developer to always return broken content
        from ma_set.agents.developer import DeveloperResult

        class BrokenDev(DeveloperAgent):
            def run(self, **kw):
                self._emit(kw.get("run_id", "x"), "agent_started", {})
                return DeveloperResult(
                    success=True, diff="",
                    files_changed=["demo_target/app.py"],
                    patched_contents={"demo_target/app.py": "# broken — no routes\n"},
                )

        broken_dev = BrokenDev(adapter, pf, project_root=tmp_path, event_callback=events.append)
        loop = DeveloperTesterLoop(
            adapter=adapter, path_filter=pf, project_root=tmp_path,
            design_spec="[stub]", max_retries=2, event_callback=events.append,
        )
        loop._developer = broken_dev   # inject broken developer
        result = loop.run()
        assert result.success is False
        assert result.escalation_report != ""
        assert any(e["event_type"] == "run_escalated" for e in events)


# ============================================================
# P1.6 — End-to-end event emission smoke test
# ============================================================

class TestEventEmission:

    def test_full_phase1_run_produces_all_key_events(self, tmp_path):
        _make_project(tmp_path)
        events = []
        adapter = _stub_adapter(events)
        pf = _make_filter(tmp_path, events)
        loop = DeveloperTesterLoop(
            adapter=adapter, path_filter=pf, project_root=tmp_path,
            design_spec="[stub]", max_retries=3, event_callback=events.append,
        )
        loop.run()
        types = {e["event_type"] for e in events}
        required = {
            "run_started", "agent_started", "llm_stub_response",
            "file_write_allowed", "diff_produced",
            "sandbox_command", "sandbox_result",
            "test_results", "agent_finished", "run_finished",
        }
        missing = required - types
        assert not missing, f"Missing event types: {missing}"
