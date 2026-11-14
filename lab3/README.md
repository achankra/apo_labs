# Lab 3 — Multi-Agent Diagnosis and Orchestration

**Duration:** 45 minutes total · 20 min in-class · 25 min take-home  
**Builds on:** Labs 1 and 2  
**Goal:** Extend the single-agent system into a multi-agent architecture where specialist agents diagnose concurrently and an orchestrator resolves conflicts with deterministic arbitration rules.

---

## Legend

| Marker | Meaning |
|---|---|
| 🟢 **PROVIDED** | Already in the repo — just run it |
| ✏️ **YOUR TASK** | You implement this during the lab |
| 🔵 **RUN** | Execute this command |

---

## Architecture

```
incident trigger
      │
      ▼
┌─────────────────────────────────────────────┐
│              Orchestrator                    │
│  fan-out (asyncio) → arbitrate → ActionAgent│
└──────┬──────────────────────┬───────────────┘
       │                      │
  ┌────┴─────┐          ┌─────┴────┐
  │ Metrics  │          │  Logs    │
  │  Agent   │          │  Agent   │
  │ (w=1.5)  │          │ (w=1.2)  │
  └──────────┘          └──────────┘
```

**Key design principles:**
- Agents run **concurrently** (asyncio fan-out), not sequentially
- Each agent has a 50 ms timeout — a slow agent never blocks the system
- Arbitration is **deterministic** (5 rules, no ML)
- ActionAgent re-evaluates gates before every execution

---

## What you'll implement

| Component | Status | Timing | Description |
|---|---|---|---|
| `AgentFinding` dataclass | 🟢 **PROVIDED** | — | Return type for every specialist agent |
| `ArbitrationResult` dataclass | 🟢 **PROVIDED** | — | Final consensus produced by arbitrator |
| `SIMULATED_*_FINDING` dicts | 🟢 **PROVIDED** | — | Canned findings for simulate mode |
| `LOG_PATTERNS` dict | 🟢 **PROVIDED** | — | Log string → symptom class mapping |
| `AGENT_WEIGHTS` dict | 🟢 **PROVIDED** | — | Per-agent weighting for consensus |
| `ActionAgent.act()` | 🟢 **PROVIDED** | — | Re-evaluates gates and executes |
| `MetricsAgent.diagnose()` | ✏️ **YOUR TASK** | In-class | Query Prometheus, score, return finding |
| `LogsAgent.diagnose()` | ✏️ **YOUR TASK** | In-class | Scan kubectl logs, pattern-match, return finding |
| `arbitrate(findings)` | ✏️ **YOUR TASK** | Take-home | Apply 5 deterministic rules, return consensus |
| `Orchestrator.run()` | ✏️ **YOUR TASK** | Take-home | asyncio fan-out + arbitrate + act |

---

## Prerequisites

All previous lab code working:

**macOS / Linux:**

```bash
python3 lab1/gate_starter.py --simulate              # 4/4 passed
python3 lab1/diagnostic_agent_starter.py --simulate  # DECISION: Execute
python3 lab2/autonomous_agent_starter.py --simulate  # Recovered in Ns
```

**Windows:**

```cmd
python lab1\gate_starter.py --simulate
python lab1\diagnostic_agent_starter.py --simulate
python lab2\autonomous_agent_starter.py --simulate
```

---

---

# 🏫 IN-CLASS — 20 minutes

> [!NOTE]
> **In-class goal:** Implement both specialist agents in simulate mode. By the end of this block each agent runs independently and returns a valid `AgentFinding` with the correct symptom class and confidence score.

---

## ✏️ Step 1 — Implement `MetricsAgent.diagnose()`

> [!IMPORTANT]
> **YOUR TASK (in-class)** — Open `orchestrator_starter.py`. Implement `MetricsAgent.diagnose(deployment, namespace)`.
>
> **Simulate mode** (required for the lab exercise):
> 1. `await asyncio.sleep(0.03)` — simulated latency
> 2. Return an `AgentFinding` built from `SIMULATED_METRICS_FINDING`
>
> **Real mode** (optional — requires live cluster):
> 1. Run `MetricsReader.read()` in an executor (non-blocking)
> 2. Apply `detect_symptom_class()` and `ConfidenceScorer`
> 3. Return `AgentFinding(agent_name="metrics", ...)`
>
> ```python
> loop = asyncio.get_event_loop()
> metrics = await loop.run_in_executor(
>     None,
>     lambda: MetricsReader(self.client, deployment, namespace).read()
> )
> ```

> [!TIP]
> **PROVIDED** — `MetricsAgent.WEIGHT = 1.5`, `SIMULATED_METRICS_FINDING`, and all Lab 1 imports are already at the top of the file.

---

## ✏️ Step 2 — Implement `LogsAgent.diagnose()`

> [!IMPORTANT]
> **YOUR TASK (in-class)** — Implement `LogsAgent.diagnose(deployment, namespace)`.
>
> **Simulate mode:** `await asyncio.sleep(0.05)`, return `SIMULATED_LOGS_FINDING`.
>
> **Real mode:**
> 1. Run `kubectl logs deployment/{deployment} -n {namespace} --since=10m` via subprocess in an executor
> 2. Count occurrences of each `LOG_PATTERNS` entry in the output
> 3. Map the most-frequent pattern to a symptom class
> 4. Set confidence by occurrence count:
>
> | occurrences | confidence |
> |---|---|
> | ≥ 5 | 0.90 |
> | ≥ 3 | 0.75 |
> | ≥ 1 | 0.60 |
> | 0   | 0.30 |

> [!TIP]
> **PROVIDED** — `LogsAgent.WEIGHT = 1.2`, `LOG_PATTERNS`, and `SIMULATED_LOGS_FINDING` are already in the starter file.

Smoke-test your two agents:

**macOS / Linux:**

```bash
python3 orchestrator_starter.py --simulate
# Expected: NotImplementedError: Implement arbitrate() — that means your agents ran
```

**Windows:**

```cmd
python orchestrator_starter.py --simulate
```

---

---

# 🏠 TAKE-HOME — 25 minutes

> [!NOTE]
> **Take-home goal:** Implement the arbitration engine and the fan-out orchestrator.

---

## ✏️ Step 3 — Implement `arbitrate(findings)`

> [!IMPORTANT]
> **YOUR TASK** — Implement `arbitrate(findings)`. Apply all 5 rules **in order**:
>
> **Rule 1 — Timeout penalty**
> For each agent that timed out: `confidence -= 0.05`. Append `"timeout_penalty: {agent_name}"`.
>
> **Rule 2 — Contradiction penalty**
> If MetricsAgent and LogsAgent disagree on `symptom_class`: both lose 0.15. Append `"contradiction: metrics={...} vs logs={...}"`.
>
> **Rule 3 — Corroboration bonus**
> If MetricsAgent and LogsAgent agree: both gain 0.10 (cap at 1.0). Append `"corroboration: {symptom_class}"`.
>
> **Rule 4 — Cascade override**
> If ANY agent finds `DEPLOYMENT_REGRESSION` with `confidence >= 0.80`: return immediately with `action_id="config.rollback"`. Append `"cascade_override: DEPLOYMENT_REGRESSION"`.
>
> **Rule 5 — Weighted consensus**
> ```
> score(symptom) = Σ weight × confidence  for each non-timed-out agent
> agreed         = argmax score(symptom)
> final_confidence = max confidence among agents for agreed symptom
> ```
> Weights: MetricsAgent = 1.5, LogsAgent = 1.2, all others = 1.0.

> [!TIP]
> **PROVIDED** — `AGENT_WEIGHTS` dict and `ACTION_MAP` (symptom class → action_id) are already defined in the starter.

---

## ✏️ Step 4 — Implement `Orchestrator.run()`

> [!IMPORTANT]
> **YOUR TASK** — Implement `Orchestrator.run(deployment, namespace)` using the fan-out pattern:
>
> ```python
> async def safe(coro, name):
>     try:
>         return await asyncio.wait_for(coro, timeout=self.FAN_OUT_TIMEOUT_S)
>     except asyncio.TimeoutError:
>         return AgentFinding(agent_name=name, timed_out=True, confidence=0.0,
>                             symptom_class="UNKNOWN", action_id="escalate_human",
>                             evidence={}, duration_ms=50)
>
> findings = list(await asyncio.gather(
>     safe(self.metrics_agent.diagnose(deployment, namespace), "metrics"),
>     safe(self.logs_agent.diagnose(deployment, namespace),    "logs"),
> ))
> ```
>
> Then call `arbitrate(findings)` and `await self.action_agent.act(...)`.

> [!TIP]
> **PROVIDED** — `Orchestrator.FAN_OUT_TIMEOUT_S = 0.050` (50 ms), the fully wired `ActionAgent`, and the `main()` entry point are all in the starter.

---

## 🔵 Step 5 — Run the full pipeline

**macOS / Linux:**

```bash
python3 orchestrator_starter.py --simulate
```

**Windows:**

```cmd
python orchestrator_starter.py --simulate
```

Expected:

```
✅  metrics     → MEMORY_PRESSURE         C=0.84 (30ms)
✅  logs        → MEMORY_PRESSURE         C=0.76 (50ms)
Arbitration rules: ['corroboration: MEMORY_PRESSURE']
Consensus: MEMORY_PRESSURE → pod.rolling_restart  C=0.9400
Action: EXECUTED (total wall time ~90ms)
```

---

## 🔵 Step 6 — Test arbitration edge cases

**Contradiction test:** Temporarily edit `SIMULATED_LOGS_FINDING` to set `symptom_class="DB_BOTTLENECK"`. Rerun — the contradiction penalty should fire and reduce both agents' confidence.

**Cascade override test:** Set `SIMULATED_METRICS_FINDING` to `symptom_class="DEPLOYMENT_REGRESSION"` and `confidence=0.85`. Verify the cascade override returns `config.rollback` regardless of the logs agent.

**Timeout test:** Temporarily add `await asyncio.sleep(0.1)` inside `MetricsAgent.diagnose()`. Verify the agent returns `timed_out=True` and the timeout penalty fires.

---

## Success Criteria

**In-class:**
- [ ] Both `MetricsAgent.diagnose()` and `LogsAgent.diagnose()` return valid `AgentFinding` objects in simulate mode
- [ ] Running the starter raises `NotImplementedError: Implement arbitrate()` — not an import error

**Take-home:**
- [ ] Full pipeline runs in simulate mode in < 200 ms
- [ ] Corroboration bonus appears in `rules_applied` when both agents agree
- [ ] Contradiction penalty appears when agents disagree
- [ ] Cascade override fires for `DEPLOYMENT_REGRESSION` + C ≥ 0.80
- [ ] A timed-out agent returns `timed_out=True` and doesn't block the pipeline

---

## Advanced Exercises

**A. Circuit breaker:** Add a `CircuitBreaker` class that blocks an agent if it has timed out more than 3 times in the last 5 minutes.

**B. EventAgent:** Add an `EventAgent` (weight 1.0) that queries `kubectl get events` for `Warning` events and includes it in the fan-out.

**C. Loki audit stream:** Replace the JSONL file logger from Lab 2 with an async HTTP push to `http://localhost:3100/loki/api/v1/push`.

**D. Grafana dashboard:** Create `grafana_dashboard.json` with panels for confidence score over time, gate rejection rate, agent timeout rate, and MTTR histogram.

**E. Training dataset:** After each `RECOVERED` outcome, write a record to `training_data.jsonl`: `{metrics, symptom_class, action_id, outcome, mttr_seconds}`.

---

## Files in this lab

```
lab3/
├── orchestrator_starter.py    ✏️ IN-CLASS (Steps 1–2) + TAKE-HOME (Steps 3–4)
├── solution/
│   └── orchestrator.py        🟢 PROVIDED — reference after you attempt the lab
└── README.md
```
