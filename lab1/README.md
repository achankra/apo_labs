# Lab 1 — Your First Confidence Gate

**Duration:** 45 minutes total · 20 min in-class · 25 min take-home  
**Repo:** `github.com/platformetrics/apo-003-labs`  
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

| Tool | Min version | Install |
|---|---|---|
| Docker Desktop | 4.x (8 GB RAM, 4 CPUs) | docker.com |
| k3d | 5.x | `brew install k3d` or k3d.io |
| kubectl | 1.27+ | bundled with Docker Desktop |
| Python | 3.11+ | python.org |

```bash
docker version && k3d version && kubectl version --client && python3 --version
```

---

---

# 🏫 IN-CLASS — 20 minutes

> [!NOTE]
> **In-class goal:** Get the cluster running and implement the four safety gates. By the end of this block your gate tests pass and you can see real metrics flowing into Prometheus.

---

## 🔵 Step 1 — Create the k3d cluster

```bash
k3d cluster create apo-lab --agents 2
kubectl get nodes   # expect: 1 server + 2 agents = Ready
```

---

## 🟢 Step 2 — Build and load payment-service

> [!TIP]
> **PROVIDED** — `lab1/payment-service/` is complete. `app.py` is a FastAPI service with `/checkout`, `/toggle_fault`, `/metrics`, and `/health`. Do not modify any of these files.

```bash
cd lab1/payment-service
docker build -t payment-service:lab .
k3d image import payment-service:lab -c apo-lab
kubectl apply -f deployment.yaml
kubectl rollout status deployment/payment-service
kubectl get pods   # expect: 2/2 Running

kubectl port-forward svc/payment-service 8080:80 &
curl http://localhost:8080/health     # {"status":"healthy"}
curl http://localhost:8080/metrics    # Prometheus text format
```

---

## 🟢 Step 3 — Deploy Prometheus

> [!TIP]
> **PROVIDED** — `lab1/prometheus-config.yaml` contains the scrape config, Prometheus Deployment, and NodePort Service. Do not modify this file.

```bash
kubectl create namespace monitoring
kubectl create configmap prometheus-config \
  --from-file=prometheus.yml=../prometheus-config.yaml \
  -n monitoring
kubectl apply -f ../prometheus-config.yaml
kubectl rollout status deployment/prometheus -n monitoring

kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
# Open http://localhost:9090/targets — payment-service should appear as UP
```

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

Lab thresholds:

| Gate | Lab limit | Prod limit |
|---|---|---|
| Cost | $500/hr | $1,000/hr |
| Blast radius | 10% of pods | 5% |
| Reversal time | 600 s | 300 s |
| Peak hours | block 09:00–17:00 UTC | same |

```bash
python gate_starter.py --simulate
# Expected: 4/4 tests passed
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

```bash
python diagnostic_agent_starter.py --simulate
```

Expected:

```
Symptom class:  MEMORY_PRESSURE
C (Composite):  0.84xx
✅  DECISION: Execute pod.rolling_restart on payment-service
```

---

## 🔵 Step 6 — Inject a fault and observe *(bonus — real cluster only)*

```bash
curl -X POST http://localhost:8080/toggle_fault   # fault ON
# Wait ~30 s for Prometheus scrape, then:
python diagnostic_agent_starter.py --prometheus-url http://localhost:9090
curl -X POST http://localhost:8080/toggle_fault   # fault OFF
```

Observe that fault injection raises error metrics, increases confidence, and the agent recommends `pod.rolling_restart`.

---

## Success Criteria

**In-class:**
- [ ] `python gate_starter.py --simulate` reports **4/4 tests passed**
- [ ] Prometheus `/targets` shows payment-service as **UP**
- [ ] Blast radius > 10% blocks the action (gate_starter.py blast-radius test fails)

**Take-home:**
- [ ] `python diagnostic_agent_starter.py --simulate` outputs correct symptom class and decision
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
