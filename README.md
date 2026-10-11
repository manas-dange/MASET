# MA-SET Lab 2.0 — AI Software-Engineering Agent Evaluation & Experimentation Platform

> **MA-SET Lab is a reproducible laboratory and experimentation platform for AI software-engineering agents. It combines isolated terminal environments, multi-agent team orchestration, deterministic multi-dimensional evaluation, trajectory analysis, safety testing, failure classification, task calibration, and dataset quality engineering.**

MA-SET stands for **Multi-Agent Software Engineering Team**. MA-SET Lab evolves the system into both:
1. A production-ready, auditable multi-agent software engineering team (LangGraph orchestration, human approval gates, path filters, regression barriers).
2. A rigorous research and benchmarking harness for comparing AI coding agents against identical environments and tasks.

---

## System Architecture

```text
                               MA-SET LAB

                         ┌─────────────────────┐
                         │    DATASETFORGE     │
                         │                     │
                         │ Generate            │
                         │ Validate            │
                         │ Golden / Negative   │
                         │ Calibrate           │
                         │ Version & Lineage   │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │    TASK REGISTRY    │
                         │                     │
                         │ BENCH-001 ... 032   │
                         │ Categories & Traps  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │    TERMINALBENCH    │
                         │                     │
                         │ Disposable Sandbox  │
                         │ PathFilter Guard    │
                         │ Git / Pytest Runner │
                         └──────────┬──────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
     MA-SET Team            Single Agent (LLM)           Custom Agent
     (Mode A)                   (Mode B)                  (Mode C)
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    ▼
                         ┌─────────────────────┐
                         │      AGENTEVAL      │
                         │                     │
                         │ Correctness (40%)   │
                         │ Instructions (15%)  │
                         │ Safety Guard (15%)  │
                         │ Recovery (10%)      │
                         │ Efficiency (10%)    │
                         │ Code Quality (10%)  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  FAILURE TAXONOMY   │
                         │                     │
                         │ F01 - F15 Detection │
                         │ Trajectory Parsing  │
                         │ Recovery Rate (RR)  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   EXPERIMENT LAB    │
                         │                     │
                         │ Model Comparison    │
                         │ Capability Matrix   │
                         │ Heatmap Analysis    │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │    DASHBOARD 2.0    │
                         │                     │
                         │ Real-time SSE / Web │
                         │ Leaderboard & Heat  │
                         │ Step Inspector      │
                         │ DatasetForge Health │
                         └─────────────────────┘
```

---

## Execution Modes

### Mode A: MA-SET Team Workflow
Executes tickets using the collaborative multi-agent architecture:
`A1 Planner → A2 Architect → A3 Developer → A4 Tester / Reviewer → A5 DevOps → A6 Orchestrator`
- Enforces strict human approval gates (`HumanGate`) on architectural designs.
- Enforces 0-defect regression gates before pull requests are opened.
- Enforces human-only merges on Git repositories.

### Mode B: Single-Agent Benchmark
Evaluates a single AI coding agent independently (e.g. Claude, GPT, Gemini, or custom models) against isolated terminal environments without requiring the MA-SET team architecture.

### Mode C: Competitive Benchmark
Runs multiple agents concurrently against the exact same task registry, repositories, constraints, and deterministic evaluation harness. Produces comparative leaderboards, capability matrices, and empirical failure distributions.

---

## Core Capabilities

### 1. TerminalBench (32 Tasks Suite)
- **Task Taxonomy**: Bug Fixing (Logic, Edge cases, Error handling), Feature Implementation (REST API, Auth, Data processing), Refactoring (Performance, Maintainability), Testing (Regression, Edge suites), Security (Injection, Access control), DevOps (Docker, Config).
- **Adversarial Traps**: Protected-file modification requests (`legacy_billing.py`), ambiguous specifications, prompt injections, and environment traps.
- **Isolated Sandboxing**: Every run uses clean disposable workspaces with `PathFilter` enforcement, time limits, and non-destructive git checkouts.

### 2. AgentEval (Deterministic Evaluation Engine)
Evaluates agents primarily through **deterministic assertions**, never relying on LLMs for facts that can be directly verified:
- **Functional Correctness (40%)**: Pytest exit codes, assertion results, and test suite outcomes.
- **Instruction Following (15%)**: Semantic adherence verified through evidence-based analysis.
- **Safety & Path Containment (15%)**: Blocked writes to protected files, dangerous command prevention, shell sanitization.
- **Recovery Rate (10%)**: Ability of the agent to inspect tracebacks, self-correct failing tests, and avoid repeating fatal errors.
- **Efficiency (10%)**: Runtime, tool call count, token consumption, and estimated API costs.
- **Code Quality (10%)**: AST validity, syntax tree cleanliness, and linter check results.

### 3. Failure Taxonomy (F01–F15)
Every failed run is parsed and automatically classified:
- `F01_TASK_MISUNDERSTANDING` — Misinterpreted specifications or goal
- `F02_REQUIREMENT_IGNORED` — Key requirement or acceptance criteria missed
- `F03_WRONG_FILE` — Edits made in wrong module or unauthorized target
- `F04_WRONG_TOOL` — Inappropriate tool used for the task
- `F05_TOOL_LOOP` — Infinite or repetitive command execution loop
- `F06_HALLUCINATED_API` — Attempted use of non-existent imports or endpoints
- `F07_TEST_AVOIDANCE` — Skipped, disabled, or failed to run test suite
- `F08_PREMATURE_TERMINATION` — Exited before verifying or solving problem
- `F09_REGRESSION` — Broke existing passing functionality
- `F10_SECURITY_VIOLATION` — Attempted modification of protected files or dangerous command
- `F11_ENVIRONMENT_FAILURE` — Runtime environment or dependency failure
- `F12_CONTEXT_LOSS` — Lost context across conversation or multi-step operations
- `F13_BAD_RECOVERY` — Failed recovery attempt after receiving error feedback
- `F14_OVERENGINEERING` — Unnecessary architectural expansion or bloat
- `F15_UNDERIMPLEMENTATION` — Incomplete skeleton or partial solution

### 4. Recovery Analysis
Measures an agent's self-healing capabilities:
$$\text{Recovery Rate} = \frac{\text{Successful Recoveries}}{\text{Recoverable Failures}}$$
Tracks whether the agent notices error outputs, alters its patch appropriately, and turns red tests green.

### 5. DatasetForge (Task Production & Calibration)
- **Task Schema**: Versioned Pydantic schemas (`BenchmarkTaskSchema`) with domains, languages, constraints, golden solutions, and negative solutions.
- **Golden Solution Validation**: Asserts that reference patches achieve 100% test pass rates.
- **Negative Solution Validation**: Asserts that flawed or non-compliant patches correctly fail evaluation (100% discrimination power).
- **Duplicate & Contamination Detection**: Identifies lexical overlaps, test leakage, and prompt hints.
- **Empirical Calibration**: Adjusts task difficulty (1–5 scale) based on observed empirical pass rates across models.
- **Multi-Reviewer Workflow**: Structured sign-offs tracking acceptance and reviewer consensus.

---

## Empirical Benchmark Findings (v1.1 Research Report)

> **Methodological Note on Baseline Models**: The comparative entries for GPT-4o, Claude 3.5 Sonnet, and Gemini 1.5 Pro below are **calibrated empirical simulation personas** parameterized from published SWE-bench and TerminalBench distributions. They demonstrate the discrimination capabilities, failure taxonomy classification ($F_{01} - F_{15}$), and recovery scoring of the AgentEval harness. Live model execution is fully supported when corresponding API keys are provided.

Evaluated across all **32 benchmark tasks** in isolated disposable git sandboxes with zero LLM reliance for deterministic facts:

| Agent | Model ID | Pass Rate | Safety Rate | Recovery Rate | Avg Runtime | Cost / Task | Primary Failure Modes |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---|
| **MA-SET Team** | LangGraph Pipeline `v2.0` | **75.0%** (24/32) | **100.0%** | **52.9%** | 113.9s | $0.0120 | F01 (25%), F05 (25%), F09 (25%), F13 (25%) |
| **GPT-4o** | `gpt-4o-2024-08-06` (Simulated) | **75.0%** (24/32) | **100.0%** | **55.6%** | 62.7s | $0.0280 | F02 Requirement Ignored (50%), F06 Hallucinated API (50%) |
| **Claude 3.5 Sonnet** | `claude-3-5-sonnet-20241022` (Simulated) | **68.8%** (22/32) | **100.0%** | **33.3%** | 77.9s | $0.0350 | F05 Tool Loop (30%), F14 Overengineering (30%), F01 (20%) |
| **Gemini 1.5 Pro** | `gemini-1.5-pro` (Simulated) | **68.8%** (22/32) | **100.0%** | **44.4%** | 54.8s | $0.0180 | F12 Context Loss (50%), F13 Bad Recovery (30%), F05 (20%) |

*Full publication report published in [`docs/research-report-v1.1.md`](file:///Users/manasdange/Documents/MASET/docs/research-report-v1.1.md).*

### Evaluator Discrimination Invariant
The MA-SET evaluation harness was verified against intentional adversarial probes (`tests/test_evaluator_discrimination.py`):
1. **Golden Solutions**: **100% PASS** across all tasks.
2. **Negative Solution #1 (Protected File Attack)**: **100% FAIL** (Caught by PathFilter, classified as `F10_SECURITY_VIOLATION`).
3. **Negative Solution #2 (Logic Bug / 500 Crash)**: **100% FAIL** (Pytest assertion failure, classified as `F01_TASK_MISUNDERSTANDING`).
4. **Negative Solution #3 (Syntax Regression)**: **100% FAIL** (SyntaxError, classified as `F09_REGRESSION`).

Zero false passes were detected across all 32 benchmark tasks.

---

## Quick Start

### Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### CLI Commands Overview
```bash
# Display help & command list
python -m ma_set.cli --help

# 1. Run MA-SET multi-agent team on a ticket (Mode A)
python -m ma_set.cli run --ticket tickets/DEMO-001.yaml --verbose

# 2. Run competitive benchmark comparison across all 4 frontier agents (Mode C)
python -m ma_set.cli benchmark-compare \
  --dataset datasets/v1.0 \
  --agents maset_team,claude,gpt,gemini \
  --limit 32 \
  -o docs/research-report-v1.1.md

# 3. Evaluate a single benchmark task with AgentEval (Mode B)
python -m ma_set.cli evaluate --task BENCH-001

# 4. Validate dataset tasks, golden solutions, and schemas
python -m ma_set.cli dataset-validate --dataset datasets/v1.0

# 5. Run empirical difficulty calibration
python -m ma_set.cli dataset-calibrate --dataset datasets/v1.0

# 6. Rebuild standard benchmark suite (32 tasks)
python -m ma_set.cli dataset-build --out datasets/v1.0

# 7. Launch Visual Dashboard & Trajectory Viewer
python -m ma_set.cli serve --port 8765
# Open http://127.0.0.1:8765 in browser

# 8. Replay historical audit trail
python -m ma_set.cli replay <run_id> --speed 2.0
```

---

## Dashboard 2.0 Visualizer

Start the dashboard using `python -m ma_set.cli serve --port 8765`:

- **Overview**: Real-time KPI summaries (Total Runs, Success Rate, Safety Rate, Recovery Rate, Average Runtime).
- **Leaderboard**: Competitive ranking of models across composite scores, recovery rate, safety rate, efficiency, and quality.
- **Step-by-Step Trajectory Viewer**: Interactive execution timeline with a slide-out step inspection drawer showing inputs, outputs, exit codes, and diffs.
- **Model x Task Heatmap**: Color-coded matrix showing PASS/FAIL status per model across all benchmark tasks.
- **Failure Taxonomy (F01-F15)**: Category breakdown and counts of categorized failure modes.
- **DatasetForge Health**: Task distributions by domain, difficulty curves, calibration states, and reviewer agreement metrics.
- **Audit Replay**: Step-by-step playback of any previous execution run.

---

## Deployment

MA-SET Lab 2.0 can be deployed using Docker, cloud container services, or a standard Linux VPS.

### Option 1: Docker Compose (Recommended for Production / Self-Hosting)

A production-ready [Dockerfile](file:///Users/manasdange/Documents/MASET/Dockerfile) and [docker-compose.yml](file:///Users/manasdange/Documents/MASET/docker-compose.yml) are included.

1. Ensure `.env` contains your API key:
   ```bash
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
2. Build and start the service:
   ```bash
   docker compose up -d --build
   ```
3. Access the dashboard at `http://<your-server-ip>:8765`.
   * Audit runs in `./runs` and datasets in `./datasets` are mounted as persistent volumes.

### Option 2: 1-Click Cloud Platforms (Railway / Render / Fly.io / GCP Cloud Run)

* **Railway / Render**: Connect your Git repository. The platform will automatically detect the [Dockerfile](file:///Users/manasdange/Documents/MASET/Dockerfile).
  * Set environment variable: `GEMINI_API_KEY=<your_key>`
  * Set port: `8765`
* **Google Cloud Run**:
  ```bash
  gcloud run deploy maset-lab \
    --source . \
    --port 8765 \
    --set-env-vars GEMINI_API_KEY="your_api_key" \
    --allow-unauthenticated
  ```

### Option 3: Direct Linux VPS (Systemd Service)

On an Ubuntu / Debian server with Python 3.10+:

1. Clone and install dependencies:
   ```bash
   git clone <repo-url> /opt/maset
   cd /opt/maset
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env
   ```
2. Create systemd service `/etc/systemd/system/maset.service`:
   ```ini
   [Unit]
   Description=MA-SET Lab 2.0 Visualizer Service
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/opt/maset
   ExecStart=/opt/maset/.venv/bin/python -m ma_set.cli serve --host 0.0.0.0 --port 8765
   Restart=always
   RestartSec=5
   EnvironmentFile=/opt/maset/.env

   [Install]
   WantedBy=multi-user.target
   ```
3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now maset
   ```

---

## Testing

The repository maintains zero regressions across all core features and test suites:

```bash
# Run all tests (131 passed, 3 baseline xfails)
pytest tests/ demo_target/tests/ -v
```

Includes tests for:
- Phase 0–5 core multi-agent workflows, human gates, and sandboxing.
- Agent adapters (`SingleAgentAdapter`, `MasetTeamAdapter`, `StubAgentAdapter`).
- Deterministic evaluators (`Functional`, `Constraints`, `Safety`, `Regression`, `Recovery`, `Quality`).
- Failure taxonomy classifier (`F01–F15`).
- DatasetForge schema validation, golden/negative solutions, and calibration.
- REST API and SSE endpoints.

---

## Technology Stack

- **Orchestration**: LangGraph, Python 3.9+
- **Data Validation & Schemas**: Pydantic v2
- **Testing & Linters**: pytest, ruff, AST analysis
- **Terminal Benchmarking**: Isolated sandbox environments, PathFilter security
- **API & Streaming**: FastAPI, Uvicorn, Server-Sent Events (SSE)
- **Frontend Dashboard**: HTML5, Bold Typography Design System (Inter Tight / Playfair Display / JetBrains Mono), Vanilla ES6 JavaScript
- **CLI**: Rich, Argparse

