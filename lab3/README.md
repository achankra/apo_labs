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

- Agents run **concurrently** (asyncio fan-out), not sequentially — total wall-clock time is determined by the slowest agent, not the sum of all agents. For two agents each taking 50ms, concurrent execution takes 50ms; sequential execution takes 100ms. At the scale of a production orchestrator making decisions every few seconds, this difference compounds into meaningful SLO headroom.
- Each agent has a **50ms timeout** — if MetricsAgent or LogsAgent takes longer than 50ms to respond, the orchestrator does not wait. It marks that agent as timed out, applies the timeout penalty in arbitration, and proceeds with whatever other agents returned. A slow metrics backend should not cause the orchestrator to miss its own latency budget.
- Arbitration is **deterministic** — the same inputs always produce the same output. This makes the system auditable: you can replay any incident from its audit log and reproduce exactly why the agent chose the action it did. No ML model, no randomness.
- ActionAgent **re-evaluates gates before every execution** — the confidence score and gate checks in Lab 1 and Lab 2 run again, so the arbitration result alone is not sufficient to execute an action.

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
> [!TIP]
> **🤖 Claude in production:** The MetricsAgent IS a Claude LLM call in a real APO system. Rather than running `detect_symptom_class()` rules, Claude receives the raw metrics dict and returns a structured `AgentFinding` by reasoning about what the numbers mean together — high memory AND elevated restarts AND stale scrape is a different prognosis than any one of those in isolation. The rule-based path you implement here is a teachable approximation of that reasoning.


MetricsAgent queries Prometheus for the same RED metrics the Lab 1 agent used, but here it is one of several concurrent agents rather than the sole source of truth. Its weight of 1.5 reflects that quantitative time-series metrics — rates, latencies, error counts, memory ratios — are typically higher-fidelity evidence than log pattern matches. These signals are numeric, aggregated over time windows, and immune to log format changes or missing log lines. When MetricsAgent returns a strong signal and LogsAgent agrees, the arbitrator amplifies both; when only MetricsAgent returns a strong signal, its weight still pulls the consensus decisively.

`run_in_executor` is necessary because `MetricsReader.read()` uses the synchronous `requests` library to query Prometheus. Calling a blocking function directly inside an async function would freeze the event loop and negate the benefit of concurrent fan-out. Running it in an executor offloads the blocking call to a thread pool, keeping the event loop free to manage the other agents' coroutines.

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
> [!TIP]
> **🤖 Claude in production:** Pattern matching on `LOG_PATTERNS` strings is a brittle heuristic — it misses novel error messages and stack traces it has never seen. Claude would do semantic log analysis: given the last 10 minutes of logs, it reasons about whether the errors indicate a dependency failure, a resource exhaustion, or a code regression, without needing a pre-defined pattern list. It also correlates log timing with recent deployment events.


LogsAgent brings a complementary evidence channel to MetricsAgent. Metrics tell you that something is wrong — latency is elevated, error rate is rising. Logs often tell you why — a specific exception, a timeout message, a pattern in the error strings that points to the root cause. When both agents independently reach the same symptom class from different data sources (quantitative time series vs. unstructured text), the corroboration bonus in Step 3 increases the arbitrator's confidence in that diagnosis. When they disagree, the contradiction penalty reduces it, forcing the orchestrator to weight the conflict explicitly rather than silently picking one.

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
> [!TIP]
> **🤖 Claude in production:** The 5 deterministic rules you implement here are a teachable approximation of multi-source arbitration. In a real system, Claude is the arbitrator: when agents contradict, it doesn't just apply a penalty — it requests additional evidence (spawns a third agent, queries a deployment diff, checks recent config changes) before committing to a consensus. The cascade override for `DEPLOYMENT_REGRESSION` maps directly to Claude's reasoning: a confident regression signal always overrides because rollback risk is lower than continued degradation.


The arbitration rules encode the trust relationships between agents and the safety posture of the system:

- **Contradiction penalty** acknowledges that conflicting signals mean the system state is uncertain. It does not block action — it reduces confidence, which may trigger the autonomy threshold and escalate to a human instead of executing blindly on ambiguous data.
- **Corroboration bonus** rewards convergent evidence. Two independent data sources agreeing on the same diagnosis is stronger evidence than either source alone, so the bonus reflects genuine information gain.
- **Cascade override for DEPLOYMENT_REGRESSION** short-circuits the normal weighted consensus. A recent deployment causing regression is a time-sensitive incident where the correct action — rollback — is known with high confidence. Waiting for weighted consensus when one agent already has 0.80+ confidence in DEPLOYMENT_REGRESSION could waste the critical window before user impact scales.
- **Weighted consensus** ensures that more reliable agents have more influence over the final decision, while still incorporating all available evidence.

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
> [!TIP]
> **🤖 Claude in production:** The fan-out here always spins up the same two agents (Metrics + Logs). A Claude-driven orchestrator would select which specialist agents to invoke based on the alert type — a latency spike triggers a DatabaseAgent and a DependencyAgent, while an OOM triggers a MemoryProfilerAgent and a ResourceQuotaAgent. The agent roster is dynamic, not fixed, and Claude decides it at runtime.


`asyncio.gather` runs all specialist agents concurrently and waits for all of them to finish, up to the timeout. `asyncio.wait_for` applies a per-agent timeout: if MetricsAgent takes longer than 50ms, the orchestrator does not wait — it marks that agent as timed out and continues with whatever other agents returned. This design is intentional.

A production orchestrator has its own latency budget. If it must respond to an incident within 200ms, and two agents each have a 50ms budget, then gather + arbitration + action must all fit in that window. Unbounded waits for a slow agent break that budget. The 50ms timeout is chosen to be tight enough to fit inside a 100ms orchestration deadline with room for arbitration and execution latency, while being generous enough that a healthy agent (simulated at 30–50ms) always finishes in time.

The `safe()` wrapper catches the timeout, returns a valid but zero-confidence `AgentFinding` with `timed_out=True`, and lets the arbitration rules handle it cleanly. This is safer than letting `TimeoutError` propagate, which would abort the entire orchestration run rather than just penalizing the slow agent.

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
> [!TIP]
> **🤖 Claude in production:** The ~90ms wall time here is two agents over asyncio. At scale, Claude orchestrates dozens of specialist agents across a service mesh — memory, latency, dependency graph, change history, SLO budget — still within a sub-second decision window. The 50 ms per-agent timeout you implemented in `safe()` is the mechanism that makes this tractable: slow agents never block the system.


---

## 🔵 Step 6 — Test arbitration edge cases

**Contradiction test:** Temporarily edit `SIMULATED_LOGS_FINDING` to set `symptom_class="DB_BOTTLENECK"`. Rerun — the contradiction penalty should fire and reduce both agents' confidence. Notice how the final confidence score drops compared to the corroboration case, and check whether the reduced confidence changes the autonomy decision (execute vs. escalate).

**Cascade override test:** Set `SIMULATED_METRICS_FINDING` to `symptom_class="DEPLOYMENT_REGRESSION"` and `confidence=0.85`. Verify the cascade override returns `config.rollback` regardless of the logs agent's finding. This confirms that the rollback rule short-circuits weighted consensus when it fires.

**Timeout test:** Temporarily add `await asyncio.sleep(0.1)` inside `MetricsAgent.diagnose()`. Verify the agent returns `timed_out=True` and the timeout penalty fires in `rules_applied`. Notice that the pipeline still completes on time using only the logs agent's finding.

> [!TIP]
> **🤖 Claude in production:** Contradiction is the most interesting case. Rather than applying a fixed 0.15 confidence penalty, Claude would spawn a tiebreaker: a third specialist agent focused specifically on the disputed dimension, or a direct query to the deployment's change log to see if a recent rollout could explain the conflicting signals. Deterministic penalty rules are the right starting point; adaptive evidence-seeking is where production systems go next.


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

**A. Circuit breaker:** Add a `CircuitBreaker` class that blocks an agent if it has timed out more than 3 times in the last 5 minutes. This models production behaviour where a consistently slow or failing agent should be excluded from future fan-outs until it recovers.

**B. EventAgent:** Add an `EventAgent` (weight 1.0) that queries `kubectl get events` for `Warning` events and includes it in the fan-out. Kubernetes events are a third independent evidence channel that often surfaces problems — OOMKilled, BackOff, Unhealthy — before they appear in metrics.

**C. Loki audit stream:** Replace the JSONL file logger from Lab 2 with an async HTTP push to `http://localhost:3100/loki/api/v1/push`. This models a production audit pipeline where records are queryable via LogQL and join with the Prometheus metrics in Grafana.

**D. Grafana dashboard:** Create `grafana_dashboard.json` with panels for confidence score over time, gate rejection rate, agent timeout rate, and MTTR histogram. Use the JSONL audit file as the data source via a Loki datasource or a Prometheus pushgateway.

**E. Training dataset:** After each `RECOVERED` outcome, write a record to `training_data.jsonl`: `{metrics, symptom_class, action_id, outcome, mttr_seconds}`. This is the seed dataset for a future ML model that could learn which actions work best for which symptom signatures in your environment.

---

## Files in this lab

```
lab3/
├── orchestrator_starter.py    ✏️ IN-CLASS (Steps 1–2) + TAKE-HOME (Steps 3–4)
├── solution/
│   └── orchestrator.py        🟢 PROVIDED — reference after you attempt the lab
└── README.md
```
