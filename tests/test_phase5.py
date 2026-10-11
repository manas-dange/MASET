"""
Phase 5 Tests — Visualization, Streaming & Demo CLI (P5.1–P5.5)
==============================================================
Covers:
  - P5.1: FastAPI streaming server REST endpoints & SSE event delivery
  - P5.2: Static dashboard UI delivery and integrity
  - P5.3: CLI commands (run, benchmark, replay, help)
  - P5.4: Live pipeline execution via API
  - P5.5: Audit trail replay and event streaming speed controls
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from ma_set.cli import build_parser, cmd_benchmark, cmd_replay, cmd_run
from ma_set.config import Config
from ma_set.events.log import EventLog
from ma_set.events.schema import Event, EventType, new_run_id
from ma_set.viz.server import create_app


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def sample_run_log(tmp_path: Path) -> tuple[Path, str]:
    """Create a temporary run JSONL file with sample events."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id()
    log = EventLog(run_id=run_id, log_dir=runs_dir)

    ev1 = Event.make(
        run_id=run_id,
        node="A1",
        agent="planner",
        event_type=EventType.TICKET_INGESTED,
        payload={"ticket_id": "DEMO-001", "title": "Validation ticket"},
    )
    ev2 = Event.make(
        run_id=run_id,
        node="A1",
        agent="planner",
        event_type=EventType.PLAN_PRODUCED,
        payload={
            "ticket_id": "DEMO-001",
            "title": "Validation ticket",
            "summary": "Plan summary",
            "user_stories": ["As a user..."],
            "technical_tasks": ["Add validation"],
            "acceptance_criteria": ["400 on empty"],
        },
    )
    ev3 = Event.make(
        run_id=run_id,
        node="A6",
        agent="orchestrator",
        event_type=EventType.RUN_FINISHED,
        payload={"ticket_id": "DEMO-001", "status": "completed"},
    )

    log.write(ev1)
    log.write(ev2)
    log.write(ev3)

    return runs_dir, run_id


@pytest.fixture
def test_client(sample_run_log: tuple[Path, str]) -> TestClient:
    runs_dir, _ = sample_run_log
    app = create_app(runs_dir=runs_dir, project_root=Config.PROJECT_ROOT)
    return TestClient(app)


# ===========================================================================
# P5.1: FastAPI REST Endpoints
# ===========================================================================

class TestVisualizationApiEndpoints:
    def test_health_endpoint(self, test_client: TestClient):
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "runs_dir" in data

    def test_tickets_endpoint_includes_traps(self, test_client: TestClient):
        resp = test_client.get("/api/tickets")
        assert resp.status_code == 200
        data = resp.json()
        assert "tickets" in data
        tickets = data["tickets"]
        assert len(tickets) >= 1

        # Must flag adversarial traps
        trap_tasks = [t for t in tickets if t["is_trap"]]
        assert len(trap_tasks) >= 2
        trap_ids = {t["id"] for t in trap_tasks}
        assert "BENCH-006" in trap_ids
        assert "BENCH-007" in trap_ids

    def test_runs_list_endpoint(self, test_client: TestClient, sample_run_log: tuple[Path, str]):
        _, run_id = sample_run_log
        resp = test_client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        run_ids = [r["run_id"] for r in data["runs"]]
        assert run_id in run_ids

    def test_run_detail_endpoint(self, test_client: TestClient, sample_run_log: tuple[Path, str]):
        _, run_id = sample_run_log
        resp = test_client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["ticket_id"] == "DEMO-001"
        assert len(data["events"]) == 3
        assert data["plan"] is not None

    def test_run_detail_not_found(self, test_client: TestClient):
        resp = test_client.get("/api/runs/nonexistent-run-999")
        assert resp.status_code == 404

    def test_benchmark_summary_endpoint(self, test_client: TestClient):
        resp = test_client.get("/api/benchmark/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tasks"] == 10
        assert len(data["trap_tasks"]) == 2
        assert "demo_target/legacy_billing.py" in data["protected_files"]


# ===========================================================================
# P5.1: SSE Event Streaming & Replay
# ===========================================================================

class TestSSEStreaming:
    def test_replay_sse_stream_delivers_events(self, test_client: TestClient, sample_run_log: tuple[Path, str]):
        _, run_id = sample_run_log
        with test_client.stream("GET", f"/api/runs/{run_id}/stream?speed=20.0") as stream_resp:
            assert stream_resp.status_code == 200
            assert "text/event-stream" in stream_resp.headers["content-type"]

            lines = [line for line in stream_resp.iter_lines() if line]
            # Should receive SSE lines with events
            assert any("event: event" in line or "data:" in line for line in lines)
            assert any("done" in line for line in lines)

    def test_replay_sse_stream_nonexistent_run(self, test_client: TestClient):
        with test_client.stream("GET", "/api/runs/nonexistent-run/stream") as stream_resp:
            assert stream_resp.status_code == 200
            lines = list(stream_resp.iter_lines())
            assert any("error" in l for l in lines)


# ===========================================================================
# P5.2: Static Dashboard Serving
# ===========================================================================

class TestDashboardStaticServing:
    def test_index_page_returns_html(self, test_client: TestClient):
        resp = test_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "MA-SET" in resp.text
        assert "IDEF0 Multi-Agent Pipeline Map" in resp.text
        assert "app.js" in resp.text
        assert "style.css" in resp.text

    def test_static_assets_serve(self, test_client: TestClient):
        css_resp = test_client.get("/static/style.css")
        assert css_resp.status_code == 200
        assert "--accent-cyan" in css_resp.text

        js_resp = test_client.get("/static/app.js")
        assert js_resp.status_code == 200
        assert "EventSource" in js_resp.text


# ===========================================================================
# P5.3: CLI Commands
# ===========================================================================

class TestCommandLineInterface:
    def test_cli_parser_builds(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--ticket", "tickets/DEMO-001.yaml"])
        assert args.command == "run"
        assert args.ticket == "tickets/DEMO-001.yaml"

    def test_cli_run_command_executes_successfully(self, tmp_path: Path):
        run_id = new_run_id()
        args = argparse.Namespace(
            ticket="tickets/DEMO-001.yaml",
            run_id=run_id,
            stub=True,
            auto_approve=True,
            verbose=False,
        )
        exit_code = cmd_run(args)
        assert exit_code == 0

        # Verify audit log was created
        log_file = Config.RUNS_DIR / f"{run_id}.jsonl"
        assert log_file.exists()

    def test_cli_replay_command(self, sample_run_log: tuple[Path, str], monkeypatch):
        runs_dir, run_id = sample_run_log
        # Point Config.RUNS_DIR to tmp runs_dir for replay test
        monkeypatch.setattr(Config, "RUNS_DIR", runs_dir)

        args = argparse.Namespace(
            run_id=run_id,
            speed=50.0,
        )
        exit_code = cmd_replay(args)
        assert exit_code == 0

    def test_cli_benchmark_command(self, tmp_path: Path, monkeypatch):
        from ma_set.benchmark.tasks import BENCHMARK_TASKS
        report_out = tmp_path / "bench_report.md"
        args = argparse.Namespace(
            report_out=str(report_out),
            tasks=[BENCHMARK_TASKS[0]],
        )
        exit_code = cmd_benchmark(args)
        assert exit_code == 0
        assert report_out.exists()
        assert "Benchmark" in report_out.read_text(encoding="utf-8")
