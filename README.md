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

| Tool | Min version | macOS | Linux | Windows |
|---|---|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) | `sudo apt install python3` | [python.org](https://python.org) |
| Git | any | [git-scm.com](https://git-scm.com) | `sudo apt install git` | [git-scm.com](https://git-scm.com) |

### Required for real-cluster mode

> **Do this before the workshop.** Cluster setup takes 10–15 minutes on a fresh machine.

#### 1. Container runtime

**macOS** — Colima (lighter, no license requirement):

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8 --disk 60
```

**macOS** — Or Docker Desktop: download from [docker.com](https://docker.com) and allocate 8 GB RAM / 4 CPUs in Preferences → Resources.

**Linux**:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl start docker
sudo usermod -aG docker $USER   # then log out and back in
```

**Windows**: Download [Docker Desktop for Windows](https://docker.com) and enable WSL 2 integration in Settings → Resources → WSL Integration.

Verify on all platforms:

```bash
docker info
```

#### 2. k3d and kubectl

**macOS**:

```bash
brew install k3d kubectl
```

**Linux**:

```bash
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
```

**Windows** (run in PowerShell as Administrator):

```powershell
winget install Rancher.k3d
winget install Kubernetes.kubectl
```

Verify:

```bash
k3d version
kubectl version --client
```

---

## Fork & clone

1. Fork on GitHub: **github.com/achankra/apo_labs → Fork → Create fork**
2. Clone your fork and install dependencies:

```bash
git clone https://github.com/YOUR_USERNAME/apo_labs.git
cd apo_labs
pip3 install -r requirements.txt
```

> **Windows:** use `pip` instead of `pip3` if `pip3` is not on your PATH.

---

## ✅ Workshop Readiness Checkpoint

Run these before the workshop. If all four pass, you are ready.

**macOS / Linux:**

```bash
python3 lab1/gate_starter.py --simulate              # expect: 4 TODO gates defined
python3 lab1/diagnostic_agent_starter.py --simulate  # expect: ✅ DECISION: Execute
python3 lab2/autonomous_agent_starter.py --simulate  # expect: ✅ Recovered
python3 lab3/orchestrator_starter.py --simulate      # expect: Action: EXECUTED
```

**Windows:**

```cmd
python lab1\gate_starter.py --simulate
python lab1\diagnostic_agent_starter.py --simulate
python lab2\autonomous_agent_starter.py --simulate
python lab3\orchestrator_starter.py --simulate
```

All four passing with no errors = ready. Email ajay@platformetrics.com if any step fails.

---

## Cluster setup (real mode)

**macOS** — start Colima first if not already running:

```bash
colima start
```

All platforms:

```bash
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
```

Port-forwards — run each in a **separate terminal window**:

```bash
kubectl port-forward svc/payment-service 8080:80
```

```bash
kubectl port-forward -n monitoring svc/prometheus 9090:9090
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
```

**macOS** (Colima):

```bash
colima stop
```

---

## Support

Questions? Email ajay@platformetrics.com.  
Solutions are in each lab's `solution/` directory — try the lab yourself first.
