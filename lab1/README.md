# Lab 1 — Your First Confidence Gate

**Duration:** 45 minutes total · 20 min in-class · 25 min take-home  
**Repo:** `github.com/achankra/apo_labs`  
**Goal:** Deploy payment-service to k3d, instrument it with Prometheus RED metrics, implement four safety gates, and wire a diagnostic agent that scores confidence and decides whether to act autonomously.

---

## Legend

| Marker | Meaning |
|---|---|
| 🟢 **PROVIDED** | Already in the repo — just run it |
| ✏️ **YOUR TASK** | You implement this during the lab |
| 🔵 **RUN** | Execute this command |

---

## Prerequisites

| Tool | Min version | macOS | Linux | Windows |
|---|---|---|---|---|
| Docker | 24+ | Colima or Docker Desktop | `sudo apt install docker.io` | Docker Desktop |
| k3d | 5.x | `brew install k3d` | see root README | `winget install Rancher.k3d` |
| kubectl | 1.27+ | `brew install kubectl` | see root README | `winget install Kubernetes.kubectl` |
| Python | 3.11+ | [python.org](https://python.org) | `sudo apt install python3` | [python.org](https://python.org) |

Verify everything is in place:

```bash
docker info && k3d version && kubectl version --client
```

> [!NOTE]
> **macOS + Colima users:** Raise the inotify limits before creating the cluster, or k3s will fail to start with "too many open files":
> ```bash
> colima ssh -- 'sudo sysctl -w fs.inotify.max_user_watches=1048576 fs.inotify.max_user_instances=512'
> ```
> Run once per Colima session.

**macOS / Linux:**

```bash
python3 --version
```

**Windows:**

```cmd
python --version
```

---

---

# 🏫 IN-CLASS — 20 minutes

> [!NOTE]
> **In-class goal:** Get the cluster running and implement the four safety gates. By the end of this block your gate tests pass and you can see real metrics flowing into Prometheus.

---

## 🔵 Step 1 — Create the k3d cluster

A k3d cluster is a lightweight Kubernetes environment running entirely inside Docker containers on your laptop. You are creating 3 nodes: 1 control-plane node (the server that schedules workloads and manages state) and 2 worker nodes (the agents that actually run your pods). The agent count matters for the blast-radius gate in Step 4 — that gate calculates what fraction of running pods would be restarted, and that fraction depends on how many pods are spread across the nodes.

```bash
k3d cluster create apo-lab --agents 2
kubectl get nodes   # expect: 1 server + 2 agents = Ready
```

> [!TIP]
> **🤖 Claude in production:** Cluster provisioning would be an API call to your IDP, not a manual CLI command. Claude would call the platform's self-service endpoint with the workload profile (`payment-service, 2 replicas, aarch64`) and wait for the cluster ready event — no human types `k3d cluster create`.


---

## 🟢 Step 2 — Build and load payment-service

> [!TIP]
> **PROVIDED** — `lab1/payment-service/` is complete. `app.py` is a FastAPI service with `/checkout`, `/toggle_fault`, `/metrics`, and `/health`. Do not modify any of these files.

The payment-service is the target system for every lab. It is a minimal FastAPI app that simulates a production checkout endpoint. `/checkout` generates realistic latency and error metrics under normal conditions; `/toggle_fault` injects artificial high latency and elevated error rates, which is what you'll use later to trigger your APO agent. `/metrics` exposes the Prometheus-format data that Prometheus scrapes every 15 seconds.

`k3d image import` loads the locally built Docker image directly into the cluster's internal image registry, bypassing Docker Hub entirely. This is what makes the lab work offline and avoids `ImagePullBackOff` errors that happen when k3d tries to pull an image from the internet.

> [!NOTE]
> `docker build` requires Docker Hub access to pull `python:3.11-slim`. If Docker Hub is unreachable and you have a cached `payment-service:lab` from a prior run, skip the build step — verify with `docker images payment-service:lab` and go straight to `k3d image import`.

```bash
cd lab1/payment-service
docker build -t payment-service:lab .
k3d image import payment-service:lab -c apo-lab
kubectl apply -f deployment.yaml
kubectl rollout status deployment/payment-service
kubectl get pods   # expect: 2/2 Running
```

> [!TIP]
> **🤖 Claude in production:** Before the build, Claude would scan the Dockerfile and `app.py` for security issues and validate `deployment.yaml` against the team's golden-path template. After rollout it would query the `/health` endpoint and confirm pod readiness — only then signal "deploy succeeded" to the calling orchestrator.

Run port-forward in a **separate terminal window** so it stays active:

```bash
kubectl port-forward svc/payment-service 8080:80
```

Verify the service is up and exposing metrics:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/metrics
```

> **Windows:** `curl` is available in PowerShell 7+ and Windows 10 1803+. If not present, open the URLs in a browser instead.

---

## 🟢 Step 3 — Deploy Prometheus

> [!TIP]
> **PROVIDED** — `lab1/prometheus-config.yaml` contains the scrape config, Prometheus Deployment, and NodePort Service. Do not modify this file.

Prometheus is the metrics store that your APO agent reads in real mode. It scrapes the `/metrics` endpoint on the payment-service every 15 seconds, storing the RED metrics (Rate, Errors, Duration) that drive the confidence formula. Without Prometheus, the agent would have no data signal — it would not know whether the service is healthy or degraded.

The configmap approach stores the Prometheus scrape configuration as a Kubernetes resource rather than baking it into the Docker image. This means you can inspect and update the scrape config with `kubectl` just like any other workload config, and the change takes effect without rebuilding or pushing a new container image.

```bash
kubectl create namespace monitoring
kubectl create configmap prometheus-config \
  --from-file=prometheus.yml=../prometheus-config.yaml \
  -n monitoring
# prometheus-config.yaml's first document is raw Prometheus scrape config, not a K8s resource.
# Apply only the Deployment + Service (from the second document onward):
sed -n '/^apiVersion:/,$p' ../prometheus-config.yaml | kubectl apply -f -
kubectl rollout status deployment/prometheus -n monitoring
```

> [!TIP]
> **🤖 Claude in production:** Claude would inspect the service's existing SLOs and recent p99 latency history, then generate the Prometheus alerting rules with calibrated thresholds — rather than applying a static config. It would also verify that the scrape target appears as UP before marking the observability step done.


Run port-forward in a **separate terminal window**:

```bash
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

Open [http://localhost:9090/targets](http://localhost:9090/targets) — payment-service should appear as **UP**. If it shows **DOWN**, the scrape config path is wrong or the port-forward is not running.

---

## ✏️ Step 4 — Implement the four safety gates

> [!IMPORTANT]
> **YOUR TASK (in-class)** — Open `gate_starter.py`. Implement four methods inside `GateOrchestrator`. Each returns `(bool, reason_str)`.
>
> ```
> _cost_gate(proposal)          → (bool, reason_str)
> _blast_radius_gate(proposal)  → (bool, reason_str)
> _reversibility_gate(proposal) → (bool, reason_str)
> _time_gate(proposal)          → (bool, reason_str)
> ```

> [!TIP]
> **PROVIDED** — `ActionProposal` and `GateResult` dataclasses, `GateConfig` with the lab thresholds, the `evaluate()` orchestration method, and four test cases are all written. Run the tests to verify your gates.

Safety gates are binary pass/fail checks that run before any action is committed. All four must pass before the agent proceeds; a single rejection blocks execution regardless of how high the confidence score is. Each gate protects against a different failure mode:

- **Cost gate** — prevents runaway automation from exceeding your hourly spend envelope. An agent that restarts pods every 5 minutes at $1,200/hr cost would quickly exceed budget even if each individual action is correct.
- **Blast radius gate** — ensures no single remediation action touches more than a fixed fraction of running pods at once. A rolling restart that hits 100% of pods simultaneously is an outage, not a fix.
- **Reversibility gate** — rejects actions that cannot be undone faster than your incident SLO. If reverting an action takes 20 minutes and your SLO is a 5-minute restore time, the action itself becomes the incident.
- **Time gate** — enforces change-freeze windows during peak traffic hours. Even a correct action carries higher blast radius when traffic is at its daily maximum.

Lab thresholds:

| Gate | Lab limit | Prod limit |
|---|---|---|
| Cost | $500/hr | $1,000/hr |
| Blast radius | 10% of pods | 5% |
| Reversal time | 600 s | 300 s |
| Peak hours | block 09:00–17:00 UTC | same |

> [!TIP]
> **🤖 Claude in production:** The thresholds in `GateConfig` are hand-coded constants for the lab. In a live system, Claude would derive these from historical incident data — calculating the blast-radius limit that kept collateral impact below SLO thresholds in past remediations, and the cost ceiling that matched the team's approved budget. The gate code stays deterministic; Claude tunes the numbers that feed it.


**macOS / Linux:**

```bash
python3 gate_starter.py --simulate
# Expected: 4/4 tests passed
```

**Windows:**

```cmd
python gate_starter.py --simulate
```

---

---

# 🏠 TAKE-HOME — 25 minutes

> [!NOTE]
> **Take-home goal:** Implement the confidence scoring engine and diagnostic agent. This is the core APO decision layer — the gates from in-class protect it, and the scorer drives it.

---

## ✏️ Step 5 — Implement the diagnostic agent

Open `diagnostic_agent_starter.py`. Implement three things:

### A. `detect_symptom_class(metrics)`

Binary gates answer "is this action allowed?" The confidence scorer answers "how certain are we that this is the right action right now?" But first the agent needs to classify what it is seeing. `detect_symptom_class` maps raw metric values to a named symptom — MEMORY_PRESSURE, DB_BOTTLENECK, etc. — that the confidence scorer and action selector then use. Without symptom classification, every incident looks the same and the agent cannot select the right remediation action.

> [!IMPORTANT]
> **YOUR TASK** — Apply these rules in order:

| Priority | Condition | Symptom class |
|---|---|---|
| 1 | `memory_usage_ratio > 0.85` | `MEMORY_PRESSURE` |
| 2 | `p99_latency_ms > 500` AND `error_rate_ratio > 0.05` | `DB_BOTTLENECK` |
| 3 | `error_rate_ratio > 0.10` | `DEPLOYMENT_REGRESSION` |
| 4 | `restart_count_1h > 5` | `CAPACITY_EXHAUSTION` |
| 5 | else | `UNKNOWN` |

### B. `ConfidenceScorer.compute(metrics, symptom_class, action_id)`

The confidence score combines four independent evidence signals into a single composite score. Using multiple signals instead of one makes the score more robust — a fresh but historically unusual metric reading gets tempered by the history signal, and a stale reading gets penalized by the freshness signal. The agent acts autonomously only when the composite score exceeds a threshold; below the threshold, it escalates to a human instead.

> [!IMPORTANT]
> **YOUR TASK** — Implement the formula: `C = 0.35×S + 0.25×H + 0.25×R + 0.15×F`

| Component | Rule |
|---|---|
| S (Signal Clarity) | mem > 0.90 → 0.95 · mem > 0.85 → 0.80 · mem > 0.75 → 0.60 · else 0.40 |
| H (Historical Match) | look up `(symptom_class, action_id)` in `HISTORICAL_MATCH` |
| R (Remediation) | look up `action_id` in `REMEDIATION_CONFIDENCE` |
| F (Freshness) | age < 30 s → 0.95 · < 60 → 0.80 · < 120 → 0.65 · else 0.40 |

### C. `PrometheusClient.query()` and `MetricsReader.read()` *(real mode only)*

> [!TIP]
> **PROVIDED** — `SIMULATED_METRICS` dict, `autonomy_level()` helper, `HISTORICAL_MATCH` and `REMEDIATION_CONFIDENCE` lookup tables, and the full `run()` orchestration are already written. The `--simulate` flag bypasses Prometheus so you can test without a cluster.

**macOS / Linux:**

```bash
python3 diagnostic_agent_starter.py --simulate
```

**Windows:**

```cmd
python diagnostic_agent_starter.py --simulate
```

Expected:

```
Symptom class:  MEMORY_PRESSURE
C (Composite):  0.84xx
✅  DECISION: Execute pod.rolling_restart on payment-service
```

---

## 🔵 Step 6
> [!TIP]
> **🤖 Claude in production:** The `detect_symptom_class()` rules and the `ConfidenceScorer` formula are your stand-in for an LLM call. In production, Claude receives the raw `metrics` dict and returns `(symptom_class, action_id, confidence_score)` using reasoning over the full metrics picture — catching compound failures (high latency AND elevated restarts AND stale scrape) that a linear rule table misses. The confidence weights (`0.35×S + 0.25×H …`) themselves would be learned from historical incident outcomes rather than hardcoded.

---

## 🔵 Step 6 — Inject a fault and observe *(bonus — real cluster only)*

`/toggle_fault` flips a flag inside the payment-service that injects artificial latency and raises the error rate. After toggling it, wait about 30 seconds for Prometheus to scrape the degraded metrics, then run the agent in real mode. You should see the agent detect the degradation, score high confidence, pass all four gates, and recommend the remediation action — the full autonomous decision loop on live data.

**macOS / Linux:**

```bash
curl -X POST http://localhost:8080/toggle_fault
# Wait ~30 s for Prometheus scrape, then:
python3 diagnostic_agent_starter.py --prometheus-url http://localhost:9090
curl -X POST http://localhost:8080/toggle_fault   # fault OFF
```

> [!TIP]
> **🤖 Claude in production:** You manually toggled the fault here. In a real APO loop, Claude watches the Prometheus alert stream. When an alert fires (`payment_service_memory_high`), it triggers the diagnostic pipeline automatically — no human action needed. After remediation it verifies the alert resolved and closes the incident ticket.


**Windows (PowerShell):**

```powershell
Invoke-WebRequest -Method POST http://localhost:8080/toggle_fault
# Wait ~30 s, then:
python diagnostic_agent_starter.py --prometheus-url http://localhost:9090
Invoke-WebRequest -Method POST http://localhost:8080/toggle_fault
```

---

---

## 🔵 Step 7 — Run in real mode (live Prometheus + Claude as the diagnostic brain)

This step runs the full APO pipeline against your live k3d cluster — no simulated data.

### What Claude does vs what the Python code does

In the APO architecture there are two distinct layers, and it matters to understand what each one does:

| Layer | Who does it | What it does |
|---|---|---|
| **Diagnostic reasoning** | **Claude (the LLM)** | Observes raw metrics, decides what is wrong, proposes a remediation action, and estimates confidence. In `diagnostic_agent_starter.py` the student implements this logic with deterministic Python rules — but in a production APO system, this layer is an LLM call: Claude reads the metrics, reasons about the symptom pattern, and returns `(symptom_class, action_id, confidence_score)` |
| **Safety gates** | **Python (`GateOrchestrator`)** | Enforces hard, non-negotiable thresholds — cost, blast radius, reversal time, peak hours. These are always pure code, never an LLM, because they must be deterministic and auditable |

**In simulate mode** (`--simulate`): Claude's reasoning layer is replaced by `SIMULATED_METRICS` + your hardcoded rules. Good for testing the gate logic without a cluster.

**In real mode** (`--prometheus-url ...`): Claude's reasoning layer reads live metrics from Prometheus. The same hardcoded rules run, but now on real signal. In a production APO agent you would replace those rules with a Claude API call that reasons over the same metrics dict.

### Prerequisites

Both port-forwards from Steps 2 and 3 must be running in separate terminals:

```bash
# Terminal 1 — payment-service
kubectl port-forward svc/payment-service 8080:80

# Terminal 2 — Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

Also install `requests` if you haven't already:

```bash
pip3 install requests
```

### Inject a fault so there is something to diagnose

**macOS / Linux:**

```bash
curl -X POST http://localhost:8080/toggle_fault
```

**Windows (PowerShell):**

```powershell
Invoke-WebRequest -Method POST http://localhost:8080/toggle_fault
```

Wait ~30 seconds for Prometheus to scrape the degraded metrics.

### Run the diagnostic agent against live Prometheus

**macOS / Linux:**

```bash
python3 diagnostic_agent_starter.py --prometheus-url http://localhost:9090
```

**Windows:**

```cmd
python diagnostic_agent_starter.py --prometheus-url http://localhost:9090
```

**What you should see:** The agent queries Prometheus for `memory_usage_ratio`, `error_rate_ratio`, `p99_latency_ms`, `restart_count_1h`, and `last_scrape_age_seconds` — the same keys as `SIMULATED_METRICS`. It classifies the symptom, scores confidence using `C = 0.35×S + 0.25×H + 0.25×R + 0.15×F`, submits an `ActionProposal` to your gates, and prints a decision. After fault injection the expected output is:

```
Symptom class:  MEMORY_PRESSURE
Proposed action: pod.rolling_restart
✅  DECISION: Execute pod.rolling_restart on payment-service
   Confidence: 0.84xx → L4 — act + notify
```

> [!NOTE]
> `MetricsReader.read()` and `PrometheusClient.query()` are TODO stubs. Until you implement them (Step 5C), the agent falls back to `SIMULATED_METRICS` automatically — you will see `"MetricsReader.read() not yet implemented — using simulated data"` in the output. Implement those methods to get live metrics flowing.

### Where Claude the LLM would replace the rules

In a real APO deployment, the `detect_symptom_class()` function and `ConfidenceScorer.compute()` are replaced by a Claude API call:

```python
# Production pattern (not part of this lab):
response = anthropic.messages.create(
    model="claude-opus-4-5",
    messages=[{"role": "user", "content": f"Metrics: {metrics}. Diagnose the symptom and propose an action."}],
    tools=[symptom_classification_tool, confidence_scoring_tool],
)
symptom_class = response.tool_use("classify_symptom")["symptom_class"]
confidence    = response.tool_use("score_confidence")["C"]
```

Claude reasons about the metrics holistically — catching composite failure patterns the rule table misses — and returns structured output that feeds directly into `ActionProposal`. The gate layer (`GateOrchestrator`) is unchanged: it validates Claude's proposal against the same hard thresholds regardless of how the proposal was generated.

The autonomy level output tells the operator how much human oversight is required based on the confidence score Claude returned.

### Turn the fault back off

**macOS / Linux:**

```bash
curl -X POST http://localhost:8080/toggle_fault
```

**Windows (PowerShell):**

```powershell
Invoke-WebRequest -Method POST http://localhost:8080/toggle_fault
```

---

## Success Criteria

**In-class:**
- [ ] Gate starter reports **4/4 tests passed** in simulate mode
- [ ] Prometheus `/targets` shows payment-service as **UP**
- [ ] Blast radius > 10% blocks the action

**Take-home:**
- [ ] Diagnostic agent outputs correct symptom class and decision in simulate mode
- [ ] C score lands between 0.80 and 0.90 for the simulated MEMORY_PRESSURE scenario
- [ ] After fault injection (real mode), the agent recommends `pod.rolling_restart`

---

## Cleanup

```bash
k3d cluster delete apo-lab
```

---

## Files in this lab

```
lab1/
├── payment-service/           🟢 PROVIDED — do not modify
│   ├── app.py
│   ├── Dockerfile
│   └── deployment.yaml
├── prometheus-config.yaml     🟢 PROVIDED — do not modify
├── gate_starter.py            ✏️ IN-CLASS — implement 4 gate methods
├── diagnostic_agent_starter.py ✏️ TAKE-HOME — implement scorer + symptom detection
├── solution/
│   ├── gate.py                🟢 PROVIDED — reference after you attempt the lab
│   └── diagnostic_agent.py   🟢 PROVIDED — reference after you attempt the lab
└── README.md
```
