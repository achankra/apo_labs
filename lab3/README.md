# Lab 3 — Multi-Agent Diagnosis and Orchestration

**Duration:** 45 minutes total · 20 min in-class · 25 min take-home  
**Builds on:** Labs 1 and 2  
**Goal:** Extend the single-agent system into a multi-agent architecture where specialist agents diagnose concurrently and an orchestrator resolves conflicts with deterministic arbitration rules.

---

## Prerequisites

Labs 1 and 2 must be complete (all simulate-mode checks pass).  
The Lab 1 cluster must be running, or `setup.sh` will start it for you.

```bash
# Quick verify before running setup.sh:
python3 ../lab1/gate_starter.py --simulate              # 4/4 passed
python3 ../lab1/diagnostic_agent_starter.py --simulate  # DECISION: Execute
python3 ../lab2/autonomous_agent_starter.py --simulate  # Recovered in Ns
```

---

## Step 1 — Start the lab environment

```bash
chmod +x setup.sh
./setup.sh
```

Reuses the Lab 1 cluster. Under 30 seconds if the cluster is already up.

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

- Agents run **concurrently** (asyncio fan-out) — total wall-clock time is the slowest agent, not the sum. At the scale of a production orchestrator, this matters.
- Each agent has a **50ms timeout** — if an agent takes longer, the orchestrator marks it timed out, applies a confidence penalty, and proceeds. A slow metrics backend should not block the incident response.
- Arbitration is **deterministic** — same inputs always produce the same output. Any incident is replayable from its audit log.
- ActionAgent **re-evaluates gates before every execution** — the confidence score and gate checks from Labs 1 and 2 run again.

---

## What you'll implement

| Component | Status | Timing | Description |
|---|---|---|---|
| `MetricsAgent.diagnose()` | ✏️ **YOUR TASK** | In-class | Query Prometheus, score, return finding |
| `LogsAgent.diagnose()` | ✏️ **YOUR TASK** | In-class | Scan kubectl logs, pattern-match, return finding |
| `arbitrate(findings)` | ✏️ **YOUR TASK** | Take-home | Apply 5 deterministic rules, return consensus |
| `Orchestrator.run()` | ✏️ **YOUR TASK** | Take-home | asyncio fan-out + arbitrate + act |
| All dataclasses, constants, `ActionAgent` | 🟢 **PROVIDED** | — | Already in starter |

---

---

# 🏫 IN-CLASS — 20 minutes

---

## Step 2 — Implement `MetricsAgent.diagnose()` ✏️

Open `orchestrator_starter.py`. Implement `MetricsAgent.diagnose(deployment, namespace)`.

**Simulate mode (required):**
1. `await asyncio.sleep(0.03)` — simulated latency
2. Return an `AgentFinding` built from `SIMULATED_METRICS_FINDING`

`SIMULATED_METRICS_FINDING` is a dict already defined in the starter. Build the return value like this:
```python
return AgentFinding(
    agent_name="metrics",
    **SIMULATED_METRICS_FINDING,   # unpacks symptom_class, action_id, confidence, evidence, duration_ms
    timed_out=False,
)
```

**Real mode (optional — requires live cluster):**
1. Run `MetricsReader.read()` in an executor (non-blocking)
2. Apply `detect_symptom_class()` and `ConfidenceScorer`
3. Return `AgentFinding(agent_name="metrics", ...)`

```python
loop = asyncio.get_event_loop()
metrics = await loop.run_in_executor(
    None,
    lambda: MetricsReader(self.client, deployment, namespace).read()
)
```

`run_in_executor` is necessary because `MetricsReader.read()` uses the synchronous `requests` library. Calling it directly inside an async function would freeze the event loop and negate the benefit of concurrent fan-out.

> **🤖 Claude in production:** MetricsAgent IS a Claude LLM call in a real APO system — Claude receives the raw metrics dict and returns a structured `AgentFinding` by reasoning about what the numbers mean together. High memory AND elevated restarts AND stale scrape is a different prognosis than any one of those in isolation.

---

## Step 3 — Implement `LogsAgent.diagnose()` ✏️

Open `orchestrator_starter.py`. Implement `LogsAgent.diagnose(deployment, namespace)`.

**Simulate mode (required):**
```python
await asyncio.sleep(0.05)
return AgentFinding(agent_name="logs", **SIMULATED_LOGS_FINDING, timed_out=False)
```

**Real mode:**
1. Run `kubectl logs deployment/{deployment} -n {namespace} --since=10m` via subprocess in an executor
2. Count occurrences of each `LOG_PATTERNS` entry in the output
3. Map the most-frequent pattern to a symptom class
4. Set confidence by occurrence count:

| occurrences | confidence |
|---|---|
| ≥ 5 | 0.90 |
| ≥ 3 | 0.75 |
| ≥ 1 | 0.60 |
| 0   | 0.30 |

> **🤖 Claude in production:** Pattern matching is brittle — it misses novel error messages. Claude does semantic log analysis: given the last 10 minutes of logs, it reasons about whether errors indicate a dependency failure, resource exhaustion, or code regression, without a pre-defined pattern list.

Smoke-test your two agents:

```bash
python3 orchestrator_starter.py --simulate
# Expected: NotImplementedError: Implement arbitrate() — that means your agents ran
```

---

---

# 🏠 TAKE-HOME — 25 minutes

---

## Step 4 — Implement `arbitrate(findings)` ✏️

Open `orchestrator_starter.py`. Find the `arbitrate(findings)` function marked `# TODO`. Apply all 5 rules **in order**:

**Rule 1 — Timeout penalty:** For each timed-out agent: `confidence -= 0.05`. Append `"timeout_penalty: {agent_name}"`.

**Rule 2 — Contradiction penalty:** If MetricsAgent and LogsAgent report *different* `symptom_class` values: subtract 0.15 from each agent's confidence. Append `"contradiction: metrics={...} vs logs={...}"`.

**Rule 3 — Corroboration bonus:** If MetricsAgent and LogsAgent report the *same* `symptom_class`: add 0.10 to each (cap at 1.0). Append `"corroboration: {symptom_class}"`.

> Rules 2 and 3 are mutually exclusive — only one fires per run.

**Rule 4 — Cascade override:** If ANY agent finds `DEPLOYMENT_REGRESSION` with `confidence >= 0.80`: return immediately with `action_id="config.rollback"`. Append `"cascade_override: DEPLOYMENT_REGRESSION"`.

**Rule 5 — Weighted consensus:**
```
score(symptom) = Σ weight × confidence  for each non-timed-out agent
agreed         = argmax score(symptom)
final_confidence = max confidence among agents for agreed symptom
```
Weights: MetricsAgent = 1.5, LogsAgent = 1.2, all others = 1.0.

> **`AGENT_WEIGHTS` dict and `ACTION_MAP` are already defined in the starter.**

The rules encode trust relationships and safety posture. Contradiction doesn't block action — it reduces confidence, which may push the autonomy level below the execution threshold. Corroboration rewards convergent evidence from two independent sources. The cascade override for `DEPLOYMENT_REGRESSION` short-circuits consensus because rollback risk is lower than continued degradation and the correct action is known.

---

## Step 5 — Implement `Orchestrator.run()` ✏️

Open `orchestrator_starter.py`. Find `Orchestrator.run()` marked `# TODO`. Implement it using the fan-out pattern:

```python
async def safe(coro, name):
    try:
        return await asyncio.wait_for(coro, timeout=self.FAN_OUT_TIMEOUT_S)
    except asyncio.TimeoutError:
        return AgentFinding(agent_name=name, timed_out=True, confidence=0.0,
                            symptom_class="UNKNOWN", action_id="escalate_human",
                            evidence={}, duration_ms=50)

findings = list(await asyncio.gather(
    safe(self.metrics_agent.diagnose(deployment, namespace), "metrics"),
    safe(self.logs_agent.diagnose(deployment, namespace),    "logs"),
))
```

Then call `arbitrate(findings)` and `await self.action_agent.act(...)`.

> `Orchestrator.FAN_OUT_TIMEOUT_S = 0.050` (50 ms), the fully wired `ActionAgent`, and `main()` are all in the starter.

---

## Step 6 — Run the full pipeline

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

## Step 7 — Test arbitration edge cases

**Contradiction:** Temporarily set `SIMULATED_LOGS_FINDING` to `symptom_class="DB_BOTTLENECK"`. Rerun — the contradiction penalty should fire. Notice how the confidence drop changes the autonomy decision.

**Cascade override:** Set `SIMULATED_METRICS_FINDING` to `symptom_class="DEPLOYMENT_REGRESSION"` and `confidence=0.85`. Verify `config.rollback` is returned regardless of the logs agent.

**Timeout:** Add `await asyncio.sleep(0.1)` inside `MetricsAgent.diagnose()`. Verify the agent returns `timed_out=True`, the timeout penalty fires, and the pipeline still completes on time using only the logs agent.

---

## Success Criteria

**In-class:**
- [ ] Both agents return valid `AgentFinding` objects in simulate mode
- [ ] Running the starter raises `NotImplementedError: Implement arbitrate()` — not an import error

**Take-home:**
- [ ] Full pipeline runs in simulate mode in < 200 ms
- [ ] Corroboration bonus appears in `rules_applied` when agents agree
- [ ] Contradiction penalty appears when agents disagree
- [ ] Cascade override fires for `DEPLOYMENT_REGRESSION` + C ≥ 0.80
- [ ] A timed-out agent returns `timed_out=True` and doesn't block the pipeline

---

## Advanced Exercises

**A. Circuit breaker:** Add a `CircuitBreaker` class that blocks an agent if it has timed out more than 3 times in the last 5 minutes.

**B. EventAgent:** Add an `EventAgent` (weight 1.0) that queries `kubectl get events` for `Warning` events and includes it in the fan-out.

**C. Training dataset:** After each `RECOVERED` outcome, write `{metrics, symptom_class, action_id, outcome, mttr_seconds}` to `training_data.jsonl` — the seed dataset for a future model that learns which actions work best for which symptom signatures.

---

## Cleanup

```bash
./teardown.sh               # stops port-forwards and load generator
../lab1/teardown.sh         # deletes the cluster (run only after all labs are done)
```

---

## Files in this lab

```
lab3/
├── setup.sh                   🟢 PROVIDED — run once at the start
├── teardown.sh                🟢 PROVIDED — run when done
├── orchestrator_starter.py    ✏️ IN-CLASS (Steps 2–3) + TAKE-HOME (Steps 4–5)
├── solution/
│   └── orchestrator.py        🟢 Reference — look after you attempt the lab
└── README.md
```
