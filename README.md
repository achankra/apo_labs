# APO Workshop Labs — Building Autonomous Operations

**Workshop:** Building Autonomous Operations: Agents for Production Safety at Speed  
**Repo:** `github.com/achankra/apo_labs`

---

## Overview

Three hands-on labs that build a full **detect → diagnose → gate → execute → verify → audit** platform, one layer at a time.

| Lab | Title | Key deliverable |
|---|---|---|
| Lab 1 | Your First Confidence Gate | Confidence scorer + 4 safety gates |
| Lab 2 | Single-Agent Autonomous Remediation | Execution loop + verification + JSONL audit |
| Lab 3 | Multi-Agent Diagnosis and Orchestration | asyncio fan-out + arbitration rules |

Each lab has a **simulate mode** (`--simulate`) that requires no cluster, no Prometheus, and no Claude API spend. Use it to get through the logic quickly, then switch to real mode for the full experience.

---

## Prerequisites

### Required (all modes)

| Tool | Min version | Install |
|---|---|---|
| Python | 3.11+ | python.org |
| Git | any | git-scm.com |

### Required for real-cluster mode

> **Do this before the workshop.** Cluster setup takes 10–15 minutes on a fresh machine.

#### 1. Container runtime — Colima (macOS, recommended) or Docker Desktop

**Colima** is lighter than Docker Desktop and avoids the license requirement:

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8 --disk 60
```

> If you use **Docker Desktop** instead, allocate at least 8 GB RAM and 4 CPUs in Preferences → Resources.

Verify the daemon is reachable:

```bash
docker info   # must succeed before proceeding
```

#### 2. k3d and kubectl

```bash
brew install k3d kubectl
k3d version   # expect: k3d version v5.x.x
```

---

## Fork & clone

1. Fork on GitHub: **github.com/achankra/apo_labs → Fork → Create fork**
2. Clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/apo_labs.git
cd apo_labs
pip install -r requirements.txt
```

---

## Verify setup (simulate mode — no cluster needed)

```bash
python lab1/gate_starter.py --simulate              # expect: 4 TODO gates defined
python lab1/diagnostic_agent_starter.py --simulate  # expect: ✅ DECISION: Execute
python lab2/autonomous_agent_starter.py --simulate  # expect: ✅ Recovered
python lab3/orchestrator_starter.py --simulate      # expect: Action: EXECUTED
```

---

## Cluster setup (real mode)

```bash
# Start Colima if not already running
colima start

# Create the lab cluster
k3d cluster create apo-lab --agents 2
kubectl get nodes   # 1 server + 2 agents → all Ready

# Build and load payment-service
cd lab1/payment-service
docker build -t payment-service:lab .
k3d image import payment-service:lab -c apo-lab
kubectl apply -f deployment.yaml
cd ../..

# Deploy Prometheus
kubectl create namespace monitoring
kubectl create configmap prometheus-config \
  --from-file=prometheus.yml=lab1/prometheus-config.yaml \
  -n monitoring
kubectl apply -f lab1/prometheus-config.yaml

# Port-forwards — keep these running in separate terminals
kubectl port-forward svc/payment-service 8080:80 &
kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
```

---

## Lab sequence

Labs run in order — each builds on the previous. Attend the lecture module before starting the corresponding lab.

| Order | Lab | Follows module |
|---|---|---|
| 1 | Lab 1 | Confidence Scoring and Safety Gates |
| 2 | Lab 2 | Single-Agent Remediation Loop |
| 3 | Lab 3 | Multi-Agent Orchestration |

---

## Repository layout

```
apo_labs/
├── README.md                        ← this file
├── requirements.txt
├── lab1/
│   ├── payment-service/             FastAPI target service
│   │   ├── app.py
│   │   ├── Dockerfile
│   │   └── deployment.yaml
│   ├── prometheus-config.yaml
│   ├── gate_starter.py              ← implement gates here
│   ├── diagnostic_agent_starter.py  ← implement agent here
│   ├── solution/
│   │   ├── gate.py
│   │   └── diagnostic_agent.py
│   └── README.md
├── lab2/
│   ├── action_catalog.yaml          remediation action registry
│   ├── autonomous_agent_starter.py  ← implement full loop here
│   ├── solution/
│   │   └── autonomous_agent.py
│   └── README.md
└── lab3/
    ├── orchestrator_starter.py      ← implement multi-agent system here
    ├── solution/
    │   └── orchestrator.py
    └── README.md
```

---

## Cleanup

```bash
k3d cluster delete apo-lab
colima stop          # optional — stops the VM but keeps the install
```

---

## Support

Questions? Email ajay@platformetrics.com.  
Solutions are in each lab's `solution/` directory — try the lab yourself first.
