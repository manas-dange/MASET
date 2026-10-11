# MA-SET Architecture Baseline & Inventory (Phase 0 Audit)

**System Name**: Multi-Agent Software Engineering Team (MA-SET)  
**Baseline Date**: 2026-10-08  
**Evolution Goal**: MA-SET Lab 2.0 — An Evaluation, Benchmarking, Trajectory Analysis, Safety-Testing, and Dataset-Engineering Platform for Software-Engineering Agents.

---

## 1. Architectural Map of Current System

```text
                        ┌────────────────────────────────────────────────────────┐
                        │              Node A6: LangGraph Orchestrator           │
                        │    (Budget Caps, Retry Caps, Audit Persistence)        │
                        └─────────┬──────────────────────────────────────────────┘
                                  │
       ┌──────────────────────────┼─────────────────────────┐
       ▼                          ▼                         ▼
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│  A1: Planner │ ───────> │ A2: Architect│ ───────> │  Human Gate  │
│  (Refine)    │          │(Impact AST)  │          │(Sign-off)    │
└──────────────┘          └──────────────┘          └──────┬───────┘
                                                           │
                                                           ▼
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│  A5: DevOps  │ <─────── │RegressionGate│ <─────── │ A3: Developer│
│  (PR + Notes)│          │ (0 Defects)  │          │  (Sandbox)   │
└──────────────┘          └──────────────┘          └──────┬───────┘
       ▲                                                   │
       │ FB3 (Feedback Loop)                     FB1 Loop  │  FB2 Loop
       └───────────────────────────────────────────────────┴───────┘
                                                  (A4: Tester / Reviewer)
```

---

## 2. Inventory of Existing Modules & Capabilities

### 2.1 Core Framework & Orchestration (`ma_set/orchestration/`)
- **`graph.py`**: LangGraph Pregel `StateGraph` linking nodes A1 to A5 with conditional edges, retry state tracking (`fb1_retries`, `fb2_retries`), budget enforcement (`MAX_LLM_CALLS_PER_TASK`), and event sink callbacks.
- **`state.py`**: `PipelineState` TypedDict and structured `EscalationReport` rendering markdown root causes and defect tables.

### 2.2 Agents (`ma_set/agents/`)
- **`planner.py` (Node A1)**: Ingests tickets, refines ambiguous requirements into structured user stories, technical tasks, and verifiable acceptance criteria.
- **`architect.py` (Node A2)**: Uses `CodeIndex` to extract touched symbols, identify affected files, and detect overlap with protected paths (yielding `ImpactReport` and `DesignSpec`).
- **`gate.py` (Human Gate)**: Interactive, auto-approve, auto-reject, or file-based impact sign-off gate with timestamped decision records.
- **`developer.py` (Node A3)**: Implements code modifications using `PathFilter` inside disposable environments; produces unified diffs and updated file maps.
- **`tester.py` (Node A4)**: Executes `pytest` and linter in isolated sandboxes, parses failure traces into structured defect matrices (`TesterResult`).
- **`reviewer.py` (Node A4)**: Verifies code quality, security boundaries, and diff adherence (`ReviewVerdict`).
- **`devops.py` (Node A5)**: Opens Git pull request branches and generates release notes with strict human-only merge enforcement (agents cannot call `git merge`).
- **`loop.py` & `fb3_loop.py`**: Feedback loops FB1 (Dev ↔ Tester), FB2 (Reviewer ↔ Dev), and FB3 (Production Feedback -> Intake).

### 2.3 Protection & Safety (`ma_set/protection/`)
- **`path_filter.py`**: Path-level security boundary enforcing strict `ALLOW_LIST` and `DENY_LIST` (`demo_target/legacy_billing.py`, `.env`, `.git/`, `ma_set/`).
- **`sandbox.py`**: Disposable command execution runner using temporary filesystem worktrees with automatic cleanup.
- **`regression_gate.py`**: Zero-defect regression gate guaranteeing no baseline tests fail before PR delivery.

### 2.4 Event & Audit System (`ma_set/events/`)
- **`schema.py`**: Strongly typed `Event` model with enum `EventType` (lifecycle, tool calls, protection blocks, gate decisions, test runs, PRs, budget caps).
- **`log.py`**: Immutable JSONL file logging (`runs/{run_id}.jsonl`) with sequential ordering and generator-based replay.

### 2.5 Benchmark Suite (`ma_set/benchmark/`)
- **`tasks.py`**: 10 initial benchmark tasks (8 functional feature/bug tasks + 2 adversarial traps `BENCH-006` and `BENCH-007` targeting `legacy_billing.py`).
- **`runner.py`**: `BenchmarkRunner` executing suites and computing completion rate, 100% trap containment rate, LLM calls, and markdown reports.

### 2.6 Visualization & Web Dashboard (`ma_set/viz/`)
- **`server.py`**: FastAPI backend with SSE streaming (`/api/runs/{run_id}/stream`), historical run queries, and execution triggers.
- **`static/`**: Modern glassmorphic SPA (`index.html`, `style.css`, `app.js`) featuring interactive pipeline graph, live audit log, budget gauge, diff viewer, and replay scrubber.

### 2.7 Command Line Interface (`ma_set/cli.py`)
- CLI subcommands: `run`, `benchmark`, `serve`, `replay`.

---

## 3. Test Suite Baseline (113 Passing Tests)

- `tests/test_event_schema.py` (5 tests)
- `tests/test_model_adapter.py` (6 tests)
- `tests/test_phase1.py` (11 tests)
- `tests/test_phase2.py` (19 tests)
- `tests/test_phase3.py` (15 tests)
- `tests/test_phase4.py` (10 tests)
- `tests/test_phase5.py` (14 tests)
- `demo_target/tests/test_app.py` (13 tests: 10 passed, 3 intentional baseline xfails)

**Status**: 100% Green.

---

## 4. MA-SET Lab 2.0 Architectural Vision & Evolution

To transform MA-SET into **MA-SET Lab**, the following subsystems will be added/extended:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                              MA-SET LAB                                │
├─────────────────────────┬─────────────────────────┬────────────────────┤
│      DatasetForge       │      TerminalBench      │     AgentEval      │
│ ─────────────────────── │ ─────────────────────── │ ────────────────── │
│ • Schema & Versioning   │ • AgentAdapter (Multi)  │ • Deterministic    │
│ • Golden Solutions      │ • Isolated Environments │ • Failure Taxonomy │
│ • Negative Solutions    │ • 30+ Benchmark Tasks   │ • Recovery Tracker │
│ • Calibration Engine    │ • Mode A/B/C Runner     │ • LLM-as-Judge     │
└─────────────────────────┴─────────────────────────┴────────────────────┘
                                  │
                                  ▼
      ┌──────────────────────────────────────────────────────────┐
      │         Dashboard 2.0 & Trajectory Analysis              │
      │ • Trajectory Timeline      • Model × Task Heatmap        │
      │ • Agent Leaderboard        • Failure Taxonomy View       │
      │ • Capability Matrix        • Safety & Recovery Curves    │
      └──────────────────────────────────────────────────────────┘
```

**Non-Negotiable Invariants**:
1. All 113 existing baseline tests remain intact and passing.
2. The Mode A MA-SET multi-agent team remains functional.
3. Backward compatibility is strictly maintained across existing CLI commands and event schemas.
