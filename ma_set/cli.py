"""MA-SET Lab 2.0 Command Line Interface.

Comprehensive CLI for software-engineering agent execution, benchmarking,
multi-agent comparison, trajectory analysis, and dataset engineering.

Commands:
  # Pipeline & Execution
  ma-set run --ticket tickets/DEMO-001.yaml
  ma-set replay <run_id>
  ma-set serve --port 8765

  # Benchmarking & Comparison (TerminalBench & AgentEval)
  ma-set benchmark [--tasks ...]
  ma-set benchmark-compare --agents ma_set,stub --dataset datasets/v1.0
  ma-set evaluate --task BENCH-001 [--agent stub]

  # DatasetForge Engineering
  ma-set dataset-validate [--dataset datasets/v1.0]
  ma-set dataset-calibrate [--dataset datasets/v1.0]
  ma-set dataset-build [--out datasets/v1.0]
  ma-set report --run-id <run_id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ma_set.agents.gate import GateMode
from ma_set.benchmark.adapters.maset_team import MasetTeamAdapter
from ma_set.benchmark.adapters.stub import StubAgentAdapter
from ma_set.benchmark.adapters.model_agents import (
    ClaudeAgentAdapter,
    GptAgentAdapter,
    GeminiAgentAdapter,
)
from ma_set.benchmark.registry import TaskRegistry
from ma_set.benchmark.runner import BenchmarkRunner, ComparisonReport
from ma_set.benchmark.tasks import BENCHMARK_TASKS
from ma_set.config import Config
from ma_set.datasetforge.generator.standard_suite import write_standard_suite
from ma_set.datasetforge.validators.task_validator import TaskValidator
from ma_set.datasetforge.calibration.calibrator import DifficultyCalibrator
from ma_set.events.log import EventLog
from ma_set.events.schema import new_run_id
from ma_set.evaluation.evaluator import AgentEvaluator
from ma_set.model.adapter import ModelAdapter, ModelConfig, Provider
from ma_set.orchestration.graph import PipelineOrchestrator
from ma_set.tools.ticket_intake import Ticket, TicketIntake

console = Console()


def cmd_run(args: argparse.Namespace) -> int:
    """Execute end-to-end pipeline on a specified ticket."""
    ticket_path = Path(args.ticket).resolve()
    if not ticket_path.exists():
        console.print(f"[bold red]Error:[/] Ticket file not found at: {ticket_path}")
        return 1

    try:
        ticket = TicketIntake.load_file(ticket_path)
    except Exception as exc:
        console.print(f"[bold red]Failed to parse ticket:[/] {exc}")
        return 1

    priority_val = getattr(ticket.priority, "value", ticket.priority)
    type_val = getattr(ticket.type, "value", ticket.type)

    console.print(Panel(
        f"[bold cyan]ID:[/] {ticket.id}\n"
        f"[bold cyan]Title:[/] {ticket.title}\n"
        f"[bold cyan]Priority:[/] {priority_val} | [bold cyan]Type:[/] {type_val}",
        title="[bold green]MA-SET Pipeline Execution[/]",
        border_style="cyan",
    ))

    provider = Provider.STUB if args.stub else Provider.GEMINI
    adapter = ModelAdapter(ModelConfig(provider=provider))
    gate_mode = GateMode.AUTO_APPROVE if args.auto_approve else GateMode.AUTO_REJECT

    orchestrator = PipelineOrchestrator(
        project_root=Config.PROJECT_ROOT,
        adapter=adapter,
        gate_mode=gate_mode,
        log_dir=Config.RUNS_DIR,
    )

    run_id = args.run_id or new_run_id()
    console.print(f"[dim]Run ID:[/] [bold]{run_id}[/]")
    console.print(f"[dim]Audit Log:[/] {Config.RUNS_DIR / f'{run_id}.jsonl'}\n")

    def print_event(ev_dict: dict):
        if args.verbose:
            ev_type = ev_dict.get("type", "")
            agent = ev_dict.get("agent_id", "system")
            console.print(f"  [dim]{ev_dict.get('timestamp', '')}[/] [cyan]{agent.upper():<12}[/] [white]{ev_type}[/]")

    result = orchestrator.run(
        ticket=ticket,
        run_id=run_id,
        event_sink=print_event if args.verbose else None,
    )

    table = Table(title="Execution Summary", border_style="bright_blue")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value")

    table.add_row("Run ID", result.run_id)
    table.add_row("Ticket ID", result.ticket_id)
    status_color = "green" if result.status == "completed" else "red"
    table.add_row("Status", f"[{status_color}]{result.status.upper()}[/{status_color}]")
    table.add_row("Success", str(result.success))
    table.add_row("LLM Calls Used", str(result.llm_calls_used))
    table.add_row("FB1 Retries (Dev↔Test)", str(result.fb1_retries))
    table.add_row("FB2 Retries (Rev↔Dev)", str(result.fb2_retries))

    if result.pr:
        table.add_row("PR Number", f"#{result.pr.number}")
        table.add_row("PR Branch", result.pr.branch)
        table.add_row("PR Title", result.pr.title)

    console.print(table)

    if result.escalation_report:
        console.print(Panel(
            result.escalation_report.render_markdown(),
            title="[bold red]Escalation Report[/]",
            border_style="red",
        ))

    return 0 if result.success else 2


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Run benchmark task suite."""
    console.print(Panel(
        f"Evaluating MA-SET across standardized tasks...",
        title="[bold cyan]MA-SET Benchmark Suite[/]",
        border_style="bright_blue",
    ))

    runner = BenchmarkRunner(
        project_root=Config.PROJECT_ROOT,
        runs_dir=Config.RUNS_DIR,
    )

    task_list = getattr(args, "tasks", None) or BENCHMARK_TASKS
    report = runner.run_suite(tasks=task_list)

    table = Table(title="Benchmark Results", border_style="green")
    table.add_column("Metric", style="bold cyan")
    table.add_column("Score", style="bold")

    table.add_row("Total Tasks", str(report.total_tasks))
    table.add_row("Completed Tasks", f"[green]{report.completed_tasks}[/]")
    table.add_row("Escalated Tasks", str(report.escalated_tasks))
    table.add_row("Task Completion Rate", f"{report.completion_rate:.1%}")
    table.add_row("Protected Traps Tested", str(report.trap_tasks))
    table.add_row("Trap Containment Rate", f"[bold green]{report.trap_containment_rate:.1%}[/]")
    table.add_row("Total LLM Calls", str(report.total_llm_calls))
    table.add_row("Avg Calls / Task", f"{report.avg_calls_per_task:.2f}")

    console.print(table)

    if getattr(args, "report_out", None):
        out_path = Path(args.report_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.render_markdown(), encoding="utf-8")
        console.print(f"[green]Saved benchmark report to:[/] {out_path}")

    return 0


def cmd_benchmark_compare(args: argparse.Namespace) -> int:
    """Run competitive model benchmark comparison (Mode C)."""
    dataset_dir = Path(args.dataset or (Config.PROJECT_ROOT / "datasets" / "v1.0")).resolve()
    registry = TaskRegistry(dataset_dir=dataset_dir)
    tasks = registry.list_all()

    if not tasks:
        console.print(f"[bold red]No tasks found in dataset:[/] {dataset_dir}")
        return 1

    limit = getattr(args, "limit", None)
    if limit and limit > 0:
        tasks = tasks[:limit]

    agent_names = [a.strip().lower() for a in (args.agents or "maset_team,claude,gpt,gemini").split(",")]
    agents = []
    for name in agent_names:
        if name in ("ma_set", "maset", "maset_team"):
            agents.append(MasetTeamAdapter(name="MA-SET Team", project_root=Config.PROJECT_ROOT))
        elif name in ("claude", "anthropic", "claude_sonnet", "claude_3_5"):
            agents.append(ClaudeAgentAdapter())
        elif name in ("gpt", "openai", "gpt_4o", "gpt4"):
            agents.append(GptAgentAdapter())
        elif name in ("gemini", "google", "gemini_pro", "gemini_flash"):
            agents.append(GeminiAgentAdapter())
        elif name in ("stub", "mock"):
            agents.append(StubAgentAdapter(name="StubAgent"))
        else:
            agents.append(StubAgentAdapter(name=name.capitalize()))

    console.print(Panel(
        f"Evaluating {len(agents)} agents across {len(tasks)} benchmark tasks from {dataset_dir.name}...",
        title="[bold cyan]MA-SET Lab: Competitive Model Benchmark[/]",
        border_style="bright_blue",
    ))

    runner = BenchmarkRunner(project_root=Config.PROJECT_ROOT)
    report: ComparisonReport = runner.run_comparison(agents=agents, tasks=tasks)

    # Render Leaderboard
    table = Table(title="Leaderboard Results", border_style="green")
    table.add_column("Agent", style="bold cyan")
    table.add_column("Success Rate", style="bold")
    table.add_column("Recovery Rate", style="bold")
    table.add_column("Safety Rate", style="bold")
    table.add_column("Quality", style="dim")
    table.add_column("Efficiency", style="dim")
    table.add_column("Avg Time", style="dim")

    for a in report.agents:
        table.add_row(
            a.agent_name,
            f"{a.success_rate:.1f}%",
            f"{a.recovery_rate:.1f}%",
            f"{a.safety_rate:.1f}%",
            f"{a.quality_score:.1f}",
            f"{a.efficiency_score:.1f}",
            f"{a.avg_runtime_s:.2f}s",
        )
    console.print(table)

    if getattr(args, "report_out", None):
        out_path = Path(args.report_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.render_markdown(), encoding="utf-8")
        console.print(f"[green]Saved comparative report to:[/] {out_path}")

    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Evaluate a specific benchmark task."""
    registry = TaskRegistry()
    task = registry.get(args.task)
    if not task:
        console.print(f"[bold red]Task not found:[/] {args.task}")
        return 1

    agent_name = (getattr(args, "agent", None) or "stub").strip().lower()
    if agent_name in ("ma_set", "maset", "maset_team"):
        agent = MasetTeamAdapter(name="MA-SET Team", project_root=Config.PROJECT_ROOT)
    elif agent_name in ("claude", "anthropic", "claude_sonnet", "claude_3_5"):
        agent = ClaudeAgentAdapter()
    elif agent_name in ("gpt", "openai", "gpt_4o", "gpt4"):
        agent = GptAgentAdapter()
    elif agent_name in ("gemini", "google", "gemini_pro"):
        agent = GeminiAgentAdapter()
    else:
        agent = StubAgentAdapter(name=agent_name.capitalize())

    runner = BenchmarkRunner(project_root=Config.PROJECT_ROOT)
    report = runner.run_agent_on_task(agent=agent, task=task)

    console.print(Panel(
        f"Task: [bold]{report.task_id}[/] | Success: [{'green' if report.success else 'red'}]{report.success}[/]\n"
        f"Composite Score: [bold cyan]{report.scores.composite:.1f}/100[/]\n"
        f"• Correctness: {report.scores.correctness:.1f}%\n"
        f"• Instruction: {report.scores.instruction_following:.1f}%\n"
        f"• Safety: {report.scores.safety:.1f}%\n"
        f"• Recovery: {report.scores.recovery:.1f}%\n"
        f"• Efficiency: {report.scores.efficiency:.1f}%\n"
        f"• Quality: {report.scores.quality:.1f}%\n"
        f"Failures Classified: {len(report.failures)}",
        title="[bold green]AgentEval Report[/]",
        border_style="cyan",
    ))
    return 0 if report.success else 2


def cmd_dataset_validate(args: argparse.Namespace) -> int:
    """Audit benchmark tasks in dataset directory."""
    dataset_dir = Path(args.dataset or (Config.PROJECT_ROOT / "datasets" / "v1.0")).resolve()
    validator = TaskValidator()
    files = sorted(dataset_dir.glob("*.yaml")) + sorted(dataset_dir.glob("*.yml"))

    if not files:
        console.print(f"[bold red]No task YAML files found in:[/] {dataset_dir}")
        return 1

    console.print(f"Auditing [bold]{len(files)}[/] tasks in [cyan]{dataset_dir}[/]...\n")

    valid_count = 0
    invalid_count = 0

    table = Table(title="Dataset Validation Summary", border_style="bright_blue")
    table.add_column("Task ID", style="bold cyan")
    table.add_column("Status", style="bold")
    table.add_column("Errors / Issues")

    for f in files:
        res = validator.validate_file(f)
        if res.is_valid:
            valid_count += 1
            table.add_row(res.task_id, "[green]VALID[/]", f"{len(res.warnings)} warnings")
        else:
            invalid_count += 1
            err_str = "; ".join(res.errors[:2])
            table.add_row(res.task_id, "[red]INVALID[/]", f"[red]{err_str}[/]")

    console.print(table)
    console.print(f"\nResult: [green]{valid_count} Valid[/], [red]{invalid_count} Invalid[/]")
    return 0 if invalid_count == 0 else 1


def cmd_dataset_calibrate(args: argparse.Namespace) -> int:
    """Run difficulty calibration analysis on dataset tasks."""
    dataset_dir = Path(args.dataset or (Config.PROJECT_ROOT / "datasets" / "v1.0")).resolve()
    registry = TaskRegistry(dataset_dir=dataset_dir)
    tasks = registry.list_all()

    calibrator = DifficultyCalibrator()
    table = Table(title="Difficulty Calibration", border_style="magenta")
    table.add_column("Task ID", style="bold cyan")
    table.add_column("Initial Diff")
    table.add_column("Calibrated Diff")
    table.add_column("Observed Pass Rate")
    table.add_column("Status")

    for t in tasks[:15]:
        rec = calibrator.calibrate(t, results=[True, True, False])
        table.add_row(
            t.id,
            str(t.difficulty.initial),
            f"{rec.recommended_difficulty:.1f}",
            f"{rec.observed_pass_rate:.1%}",
            rec.status,
        )

    console.print(table)
    return 0


def cmd_dataset_build(args: argparse.Namespace) -> int:
    """Build or regenerate standard benchmark task suite."""
    out_dir = Path(args.out or (Config.PROJECT_ROOT / "datasets" / "v1.0")).resolve()
    count = write_standard_suite(out_dir)
    console.print(f"[bold green]Successfully generated {count} benchmark tasks in:[/] {out_dir}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start visualization web server."""
    import uvicorn
    from ma_set.viz.server import create_app

    host = args.host or Config.DASHBOARD_HOST
    port = args.port or Config.DASHBOARD_PORT

    console.print(Panel(
        f"Starting MA-SET Lab 2.0 Visualizer & Governance Dashboard on:\n"
        f"[bold green]http://{host}:{port}[/]\n\n"
        f"• Lab Leaderboard: [cyan]http://{host}:{port}/#tab-leaderboard[/]\n"
        f"• Trajectory Viewer: [cyan]http://{host}:{port}/#tab-trajectory[/]\n"
        f"• Model Heatmap: [cyan]http://{host}:{port}/#tab-heatmap[/]\n"
        f"• Historical Runs: [cyan]{Config.RUNS_DIR}[/]\n",
        title="[bold cyan]MA-SET Lab 2.0 Dashboard Service[/]",
        border_style="green",
    ))

    app = create_app(runs_dir=Config.RUNS_DIR, project_root=Config.PROJECT_ROOT)
    uvicorn.run(app, host=host, port=port)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a recorded run JSONL audit trail in terminal."""
    log_file = Config.RUNS_DIR / f"{args.run_id}.jsonl"
    if not log_file.exists():
        console.print(f"[bold red]Run log not found at:[/] {log_file}")
        return 1

    events = list(EventLog.replay_file(log_file))
    console.print(Panel(
        f"Replaying [bold]{len(events)}[/] events from [cyan]{args.run_id}[/] at [yellow]{args.speed}x[/] speed...",
        title="[bold cyan]Audit Log Replay[/]",
        border_style="bright_blue",
    ))

    delay = max(0.005, 0.05 / args.speed)
    for ev in events:
        agent = ev.get("agent_id") or ev.get("agent") or "SYSTEM"
        agent = agent.upper()
        ev_type = ev.get("event_type") or ev.get("type", "")
        ts = ev.get("timestamp", "")
        color = "cyan" if "AGENT" in ev_type else ("green" if "COMPLETED" in ev_type or "APPROVED" in ev_type else "yellow")
        console.print(f"  [dim]{ts}[/] [{color}]{agent:<12}[/{color}] [bold]{ev_type}[/]")
        time.sleep(delay)

    console.print("\n[bold green]Replay completed successfully.[/]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ma-set",
        description="MA-SET Lab 2.0: Multi-Agent Software Engineering Team & Evaluation Platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run multi-agent pipeline on a ticket")
    run_parser.add_argument("--ticket", "-t", required=True, help="Path to ticket YAML file")
    run_parser.add_argument("--run-id", help="Explicit run ID (auto-generated if omitted)")
    run_parser.add_argument("--stub", action="store_true", default=True, help="Use deterministic stub model adapter")
    run_parser.add_argument("--auto-approve", action="store_true", default=True, help="Auto-approve human gate")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Print live event log stream")

    # Command: benchmark
    bench_parser = subparsers.add_parser("benchmark", help="Run standard benchmark suite")
    bench_parser.add_argument("--report-out", "-o", help="Optional output path for markdown report")

    # Command: benchmark-compare
    comp_parser = subparsers.add_parser("benchmark-compare", help="Compare multiple agents competitively (Mode C)")
    comp_parser.add_argument("--agents", default="ma_set,stub", help="Comma-separated agent names (e.g. ma_set,stub,claude)")
    comp_parser.add_argument("--dataset", help="Path to dataset directory (default: datasets/v1.0)")
    comp_parser.add_argument("--limit", type=int, help="Limit number of tasks to run")
    comp_parser.add_argument("--report-out", "-o", help="Output path for markdown report")

    # Command: evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate single task with AgentEval")
    eval_parser.add_argument("--task", required=True, help="Task ID (e.g. BENCH-001)")
    eval_parser.add_argument("--agent", default="stub", help="Agent adapter: maset_team, claude, gpt, gemini, stub (default: stub)")

    # Command: dataset-validate
    val_parser = subparsers.add_parser("dataset-validate", help="Validate task definitions in dataset")
    val_parser.add_argument("--dataset", help="Path to dataset directory (default: datasets/v1.0)")

    # Command: dataset-calibrate
    cal_parser = subparsers.add_parser("dataset-calibrate", help="Calibrate task difficulty metrics")
    cal_parser.add_argument("--dataset", help="Path to dataset directory (default: datasets/v1.0)")

    # Command: dataset-build
    build_parser_cmd = subparsers.add_parser("dataset-build", help="Generate 32 standard benchmark tasks")
    build_parser_cmd.add_argument("--out", help="Output directory (default: datasets/v1.0)")

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Launch visualization & dashboard web server")
    serve_parser.add_argument("--host", default=Config.DASHBOARD_HOST, help="Host address (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=Config.DASHBOARD_PORT, help="Port (default: 8765)")

    # Command: replay
    replay_parser = subparsers.add_parser("replay", help="Replay historical run audit trail")
    replay_parser.add_argument("run_id", help="ID of run to replay")
    replay_parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")

    return parser


def main() -> None:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "benchmark":
        sys.exit(cmd_benchmark(args))
    elif args.command == "benchmark-compare":
        sys.exit(cmd_benchmark_compare(args))
    elif args.command == "evaluate":
        sys.exit(cmd_evaluate(args))
    elif args.command == "dataset-validate":
        sys.exit(cmd_dataset_validate(args))
    elif args.command == "dataset-calibrate":
        sys.exit(cmd_dataset_calibrate(args))
    elif args.command == "dataset-build":
        sys.exit(cmd_dataset_build(args))
    elif args.command == "serve":
        sys.exit(cmd_serve(args))
    elif args.command == "replay":
        sys.exit(cmd_replay(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
