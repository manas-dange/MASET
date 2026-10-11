# MA-SET — Demo Walkthrough & Architecture Case Study

## 1. Overview & System Mission

**MA-SET** (*Multi-Agent Software Engineering Team*) is an autonomous, auditable, and security-governed pipeline that turns software engineering tickets into verified pull requests without human-level trust hazards or protected codebase modifications.

Traditional autonomous coding agents suffer from common failure modes:
1. **Unbounded edits**: Corrupting unassigned, sensitive, or legacy modules.
2. **Infinite retry loops & cost explosions**: Unconstrained LLM API billing.
3. **Ghost passes**: Merging pull requests without passing regression test suites.
4. **Unauthorized merges**: Directly altering protected branches without human engineer review.

MA-SET eliminates these failure modes by enforcing **strict, layered safety controls** inside an **IDEF0-structured multi-agent team**:

```
[ A1: Planner ] -> [ A2: Architect ] -> [ Human Gate ] -> [ A3: Developer ] -> [ A4: Tester ] -> [ A4: Reviewer ] -> [ Regression Gate ] -> [ A5: DevOps ]
                                                              ▲                  │                  │
                                                              └── FB1 (Pytest) ──┘                  │
                                                              ▲                                     │
                                                              └──────────── FB2 (Review) ───────────┘
```
Governed centrally by **Node A6: Orchestrator** enforcing LLM call caps, retry limits, and immutable JSONL audit trails.

---

## 2. Safety Guarantees & Containment Invariants

| Safety Control | Implementation | Verification Status |
|:---|:---|:---:|
| **1. Read-Only Main Branch** | Main workspace files are never dirtied or directly committed to. Edits occur in sandboxes and are delivered only via PR branches. | [YES] Verified |
| **2. Python PathFilter** | In-process file path interceptor blocking unauthorized reads/writes to denied paths (`demo_target/legacy_billing.py`, `.venv/`, `.git/`, `ma_set/`). | [YES] 100% Trap Containment |
| **3. Disposable Sandboxes** | Command execution (pytest, ruff, git diff) runs inside temporary directories discarded after each task. | [YES] Zero Leakage |
| **4. Human Sign-Off Gate** | Architect node flags any protected file overlap before code is written; requires human approval or auto-reject escalation. | [YES] Verified |
| **5. Regression Gate** | Pre-PR gate requiring 0 new defects before any branch or PR is created. | [YES] Enforced |
| **6. Human-Only Merge** | DevOps agent opens pull requests and generates release notes, but is programmatically prohibited from executing `git merge`. | [YES] Enforced |
| **7. Governance Budget Caps** | Hard budget ceiling (20 LLM calls per task) and retry caps (3 per feedback loop). | [YES] Enforced |
| **8. Audit Trail** | Every tool invocation, gate decision, LLM call, and agent action is persisted to `runs/{run_id}.jsonl`. | [YES] 100% Persistent |

---

## 3. Quick Start & CLI Workflows

Activate the virtual environment:
```bash
source .venv/bin/activate
```

### 3.1 Execute a Standard Ticket (DEMO-001)

Run the multi-agent pipeline on `tickets/DEMO-001.yaml` (adding input validation to `/signup`):

```bash
python -m ma_set.cli run --ticket tickets/DEMO-001.yaml --verbose
```

**Expected Output:**
- A1 Planner ingests and refines user stories and acceptance criteria.
- A2 Architect analyzes file impact and confirms 0 protected files touched.
- Human Gate approves impact spec.
- A3 Developer implements validation patch in a disposable sandbox.
- A4 Tester executes `pytest demo_target/tests/ -v` inside the sandbox (FB1 loop passes on attempt 1).
- A4 Reviewer approves code quality and confirms 0 protected file touch.
- Regression Gate confirms 0 test regressions.
- A5 DevOps opens Pull Request (`ma-set/demo-001` -> `main`) and generates release notes.
- Workspace root remains clean and unpatched.

### 3.2 Testing Adversarial Trap Containment (BENCH-006)

To test how MA-SET intercepts malicious or confused instructions attempting to touch `demo_target/legacy_billing.py`:

```bash
python -m ma_set.cli run --ticket tickets/BENCH-006.yaml --verbose
```
*(or run through the Web Dashboard)*

**Safety Containment Verification:**
- Architect identifies `demo_target/legacy_billing.py` as a protected file.
- PathFilter raises `PermissionError` and emits `FILE_WRITE_BLOCKED`.
- Pipeline immediately halts, containing the attack with 0 edits to billing.
- Node A6 produces an `EscalationReport` explaining the containment and notifying human operators.

### 3.3 Running the 10-Task Benchmark Suite

Evaluate the entire pipeline across 10 standardized tasks (8 functional tickets + 2 adversarial traps):

```bash
python -m ma_set.cli benchmark --report-out docs/benchmark_results.md
```

**Benchmark Results:**
- **Completion Rate**: 100% of valid tasks completed.
- **Trap Containment Rate**: 100% of adversarial attacks blocked.
- **Average LLM Calls**: ~2 calls per completed task.

---

## 4. Visual Dashboard & SSE Replay Engine

MA-SET includes a modern, glassmorphic real-time web dashboard powered by FastAPI and Server-Sent Events (SSE).

### 4.1 Launching the Dashboard

```bash
python -m ma_set.cli serve --port 8765
```
Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** in your browser.

### 4.2 Web UI Features

1. **IDEF0 Multi-Agent Pipeline Map**:
   - Visual nodes: `A1 Planner`, `A2 Architect`, `Human Gate`, `A3 Developer`, `A4 Tester`, `A4 Reviewer`, `Regression Gate`, `A5 DevOps`, `A6 Orchestrator`.
   - Dynamic node state illumination: Active nodes pulse with glowing cyan rings, completed nodes illuminate emerald checkmarks, and escalated/blocked nodes display crimson warning shields.
   - Interactive node filtering: Click any node to instantly isolate that agent's events in the audit log.

2. **Real-Time Governance Metrics Bar**:
   - **LLM Call Budget Meter**: Displays live call count against the 20-call cap with color-coded gauge.
   - **Safety Containment Status**: Shows Read-Only Main, Legacy Billing Containment, and Regression Gate status chips.
   - **Feedback Loop Retries**: Live counters for FB1 (Dev ↔ Tester) and FB2 (Reviewer ↔ Dev).

3. **Live Event Stream & Audit Trail**:
   - Millisecond timestamps, color-coded agent tags, and collapsible JSON payload inspector.
   - Filter by agent or search by event type.

4. **Multi-Tab Intelligence Panel**:
   - **Pull Request & Diff Tab**: Unified git diff viewer with syntax color-coding, branch name, PR number, and Human-Only Merge enforcement banner.
   - **Plan & Specs Tab**: User stories, technical tasks, affected files list, and symbol analysis.
   - **Escalation & Safety Tab**: Containment proof, failure cause, and recommended actions when a gate or trap is triggered.
   - **Replay Scrubber Tab**: Step back, step forward, play, pause, and scrub through recorded runs step-by-step.

5. **Playback Speed Controls**:
   - Replay saved historical runs from `runs/*.jsonl` at adjustable playback speeds (`0.5x`, `1.0x`, `2.0x`, `5.0x`) without invoking external LLMs.

### 4.3 CLI Audit Trail Replay

You can also replay any past run directly in your terminal with colored logs:
```bash
python -m ma_set.cli replay <run_id> --speed 2.0
```
