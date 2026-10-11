# MA-SET Lab 2.0: IDEF0 Functional Architecture

## Top-Level Context: A-0
**Function**: Evaluate AI Software Engineering Agents  
**Inputs**: Benchmark Task YAMLs, Candidate Agents (MA-SET, Claude, GPT, Gemini, Stubs), Base Codebases  
**Controls**: Safety Deny-Lists, Budget Caps (Calls/Loops), Pytest Ground Truth, Evaluation Methodology (v1.0)  
**Mechanisms**: IsolatedEnvironment Sandbox, LangGraph Pregel Engine, Pydantic Validators, Pytest Runner  
**Outputs**: Evaluation Reports, Model Comparison Leaderboard, Trajectory JSONL Audit Trails, Calibrated Datasets  

---

## Decomposition: Node A0

```text
                               A-0
                                │
   ┌────────────────────────────┼────────────────────────────┐
   │                            │                            │
   ▼                            ▼                            ▼
A1: Define Task          A2: Prepare Env             A3: Execute Agent
- DatasetForge           - IsolatedEnvironment       - AgentAdapter
- Schema Validation      - Sandbox Directory         - Terminal Access
- Golden Solution        - Disposable Temp Dir       - Trajectory Stream
   │                            │                            │
   └────────────────────────────┼────────────────────────────┘
                                │
   ┌────────────────────────────┼────────────────────────────┐
   │                            │                            │
   ▼                            ▼                            ▼
A4: Evaluate Result      A5: Analyze Trajectory      A6: Calibrate Dataset
- FunctionalEvaluator    - RecoveryAnalyzer          - DifficultyCalibrator
- ConstraintsEvaluator   - FailureClassifier F01-F15 - Pass Rate Analysis
- SafetyEvaluator        - Repetition & Exploration  - Drift Correction
   │                            │                            │
   └────────────────────────────┴────────────────────────────┘
                                │
                                ▼
                       A7: Report & Visualize
                       - Leaderboard & Heatmap
                       - Trajectory Visualizer
                       - Executive Research Report
```

---

## Detailed Node Specifications

### Node A1: Define Task (DatasetForge)
- **Inputs**: Raw bug reports, feature requests, adversarial trap scenarios.
- **Activities**: Authoring task YAML, schema validation via Pydantic (`BenchmarkTaskSchema`), golden patch verification, negative patch discrimination, anti-leakage audit.
- **Outputs**: Versioned task suite (`datasets/v1.0/BENCH-001.yaml` .. `BENCH-032.yaml`).

### Node A2: Prepare Environment (TerminalBench Sandbox)
- **Inputs**: Pristine target repository (`demo_target/`), task constraints.
- **Activities**: Creation of disposable ephemeral workspace, excluding `.venv` and `.git`, attaching `PathFilter` guardrails.
- **Outputs**: Pristine `IsolatedEnvironment` workspace.

### Node A3: Execute Agent (Agent Adapters)
- **Inputs**: Task prompt, sandbox terminal, budget caps.
- **Activities**: Execution via `MasetTeamAdapter` (Mode A), `SingleAgentAdapter` (Mode B), or competitive batching (Mode C).
- **Outputs**: Code modifications, command log, token usage, execution duration.

### Node A4: Evaluate Result (AgentEval Engine)
- **Inputs**: Sandbox workspace after execution, ground-truth tests.
- **Activities**: Deterministic test execution (`FunctionalEvaluator`), protected path check (`ConstraintsEvaluator`), regression check (`RegressionEvaluator`), safety containment audit (`SafetyEvaluator`).
- **Outputs**: Versioned component scores (Correctness 40%, Instruction Following 15%, Safety 15%, Recovery 10%, Efficiency 10%, Code Quality 10%).

### Node A5: Analyze Trajectory (Failure & Recovery Analysis)
- **Inputs**: Structured JSONL audit events.
- **Activities**: Dynamic recovery episode extraction (`RecoveryAnalyzer`), failure mode classification against F01–F15 taxonomy (`FailureClassifier`), exploration ratio & repetition rate calculation (`BehaviorMetricsEvaluator`).
- **Outputs**: Structured `FailureReport`, recovery rate metric, behavioral indices.

### Node A6: Calibrate Dataset (Empirical Calibration)
- **Inputs**: Multi-model run outcomes across task suites.
- **Activities**: Mapping observed pass rates to difficulty scale (1=trivial, 2=easy, 3=moderate, 4=difficult, 5=expert), flagging misaligned author ratings.
- **Outputs**: Calibrated dataset metadata.

### Node A7: Report & Visualize (MA-SET Lab Dashboard)
- **Inputs**: Evaluation reports, comparison matrices, trajectories.
- **Activities**: Serving interactive web visualizer (`ma_set.viz`), rendering step-by-step trajectory timelines, model × task heatmap, agent leaderboard, generating executive reports.
- **Outputs**: Web dashboard at `http://localhost:8765`, CLI markdown reports.
