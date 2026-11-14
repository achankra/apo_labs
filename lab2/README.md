# Lab 2 — Single-Agent Autonomous Remediation

**Duration:** 45 minutes total · 20 min in-class · 25 min take-home  
**Builds on:** Lab 1 (gate.py + diagnostic_agent.py)  
**Goal:** Extend the diagnostic agent into a fully autonomous remediation loop: detect → diagnose → gate → **execute → verify → audit**

---

## Legend

| Marker | Meaning |
|---|---|
| 🟢 **PROVIDED** | Already in the repo — just run it |
| ✏️ **YOUR TASK** | You implement this during the lab |
| 🔵 **RUN** | Execute this command |

---

## What you'll add in this lab

| Component | Status | Timing | What it does |
|---|---|---|---|
| `action_catalog.yaml` | 🟢 **PROVIDED** | — | Registry of approved remediation actions with risk metadata |
| `load_action_catalog()` | ✏️ **YOUR TASK** | In-class | Reads and parses the YAML registry |
| `ActionExecutor.execute()` | ✏️ **YOUR TASK** | In-class | Runs `kubectl rollout restart` via subprocess |
| `VerificationLoop.wait_for_recovery()` | ✏️ **YOUR TASK** | Take-home | Polls P90 latency until it drops to 1.5× baseline |
| `AuditLogger.append()` | ✏️ **YOUR TASK** | Take-home | Appends a full JSONL record per run |
| `run()` orchestration | 🟢 **PROVIDED** | — | Chains all components in order |

---

---

# 🏫 IN-CLASS — 20 minutes

> [!NOTE]
> **In-class goal:** Wire the action catalog and get the executor running in dry-run mode. By the end of this block you can see your agent select an action, pass it through the gates, and log what it would have done — without touching the cluster.

---

## 🟢 Step 1 — Inspect the action catalog

> [!TIP]
> **PROVIDED** — `action_catalog.yaml` is complete. Open it and read it; you will not modify it. Each action specifies `risk_class`, `blast_radius_max`, `reversal_time_seconds`, `required_confidence`, `max_executions_per_hour`, `cooldown_seconds`, and `symptom_classes`. This is what APO agents consult before proposing an action.
> [!TIP]
> **🤖 Claude in production:** Claude doesn't read a static YAML file — it queries a live action catalog service via API. When no approved action fits a novel symptom, Claude can draft a new candidate action and submit it for human review before it enters the catalog. The catalog itself is a living policy document Claude helps maintain.


An action catalog is the boundary of what an APO agent is authorized to do. By defining approved remediation actions as data (a YAML file) rather than code, operators can tighten or expand agent authority without modifying the agent itself or deploying a new version. Each catalog entry also carries the risk metadata that the gates in Lab 1 need — blast radius, reversal time — so the gates can evaluate any proposal without understanding the action's implementation details. The catalog is also the place where `max_executions_per_hour` and `cooldown_seconds` are enforced, preventing the agent from repeatedly executing the same action if the first attempt did not resolve the issue.

---

## ✏️ Step 2 — Implement `load_action_catalog()`

> [!IMPORTANT]
> **YOUR TASK (in-class)** — Open `autonomous_agent_starter.py`. Implement `load_action_catalog(path)`:
> 1. Open the YAML file at `path`
> 2. Parse with `yaml.safe_load`
> 3. Return a dict keyed by `action_id`

```python
import yaml
with open(path) as f:
    raw = yaml.safe_load(f)
return {a["action_id"]: a for a in raw["actions"]}
```

`yaml.safe_load` is the secure parser variant — unlike `yaml.load`, it cannot execute arbitrary Python code embedded in the YAML file. This matters for a catalog that operators edit, since a misconfigured catalog should produce a parse error, not code execution.

Install pyyaml if needed:

```bash
pip3 install pyyaml
```

> **Windows:** use `pip install pyyaml`
> [!TIP]
> **🤖 Claude in production:** Parsing the catalog is the easy part. Claude also validates it on load — checking that every `required_confidence` threshold is achievable given the formula weights, and that no action's `blast_radius_max` exceeds the global limit in `GateConfig`. Mismatches are surfaced as policy warnings before any agent runs.


---

## ✏️ Step 3 — Implement `ActionExecutor.execute()`

> [!IMPORTANT]
> **YOUR TASK (in-class)** — Implement `ActionExecutor.execute(action_id, deployment, namespace)`:
> 1. Map `action_id` to a `kubectl` command
> 2. Run via `subprocess.run` with a 30 s timeout
> 3. Return a dict with `success`, `output`, `error`, `duration_ms`, and `dry_run`/`simulate` flags
>
> For `pod.rolling_restart`:
> ```bash
> kubectl rollout restart deployment/{deployment} -n {namespace}
> ```

> [!TIP]
> **PROVIDED** — `simulate` and `dry_run` flags are wired into the starter. In simulate mode the executor returns a canned success dict without calling kubectl.

Using `subprocess.run` keeps a clean separation between the decision layer (which only scores and gates) and the execution layer (which actually calls kubectl). This boundary means you can unit-test the decision logic without a cluster, and you can audit exactly what commands the agent runs by logging `subprocess.run`'s arguments.

A rolling restart tells Kubernetes to replace each pod one at a time, waiting for the new pod to pass its readiness probe before terminating the old one. This achieves zero-downtime remediation for many classes of problems (memory leaks, stale connections, misconfigured environment variables). The `dry_run` flag lets you test the full decision path in a live environment without actually restarting any pods — useful for validating gate logic during an incident without taking additional risk.

**macOS / Linux:**

```bash
python3 autonomous_agent_starter.py --simulate --dry-run
# Expected: ✅  [DRY RUN] Executed pod.rolling_restart
```

**Windows:**

```cmd
python autonomous_agent_starter.py --simulate --dry-run
```
> [!TIP]
> **🤖 Claude in production:** `kubectl rollout restart` is one of many possible execution backends. Claude would select the execution method based on the target system's capabilities — a Kubernetes workload gets kubectl, a VM-based service gets an Ansible playbook, a managed cloud service gets an API call. The `ActionExecutor` abstraction maps to this: Claude picks the right tool for the target, not always kubectl.


---

---

# 🏠 TAKE-HOME — 25 minutes

> [!NOTE]
> **Take-home goal:** Complete the closed loop — add verification that the action actually worked, and audit logging so every decision is traceable.

---

## ✏️ Step 4 — Implement `VerificationLoop.wait_for_recovery()`

> [!IMPORTANT]
> **YOUR TASK** — Implement the recovery polling loop.
>
> **Success criterion:** P90 latency drops below **1.5× the pre-action baseline within 120 seconds.**
>
> PromQL to poll P90:
> ```
> histogram_quantile(0.90,
>   rate(http_request_duration_seconds_bucket{deployment="payment-service"}[1m])
> ) * 1000
> ```
>
> Polling pseudocode:
> ```python
> threshold_ms = baseline_p90 * 1.5
> start = time.monotonic()
> while elapsed < timeout:
>     p90 = query_prometheus(...)
>     if p90 < threshold_ms:
>         return {"recovered": True, "elapsed_seconds": elapsed, ...}
>     time.sleep(poll_interval)
> return {"recovered": False, ...}
> ```

> [!TIP]
> **PROVIDED** — In simulate mode, `wait_for_recovery()` returns `recovered: True` after one poll interval. You only need to implement the real-mode polling path.
> [!TIP]
> **🤖 Claude in production:** The 1.5× threshold and 120 s timeout are fixed constants here. Claude would derive these dynamically — using the deployment's historical p90 distribution to set a threshold that is tight enough to catch a failed recovery but not so tight it false-positives on normal traffic jitter. It would also adaptively back off the poll interval if Prometheus is under load.


Execution alone is not enough — an APO agent must confirm that the action achieved the intended outcome. A rolling restart is not guaranteed to fix every kind of degradation; if the root cause is a database bottleneck or a misconfigured environment variable, the pods will restart clean and then degrade again within minutes. The verification loop catches this case by polling P90 latency at short intervals and comparing against the pre-action baseline. 

P90 (the 90th-percentile latency) is a better verification signal than the mean because it is less sensitive to outliers and more representative of what real users experience. The 1.5× threshold gives the action credit for partial improvement — if baseline P90 was 200ms and the action brings it to 280ms, that is an improvement worth calling a success even if it is not back to baseline. The 120-second timeout is tight enough to fit inside a typical incident SLO and long enough for Kubernetes to complete a rolling restart and for Prometheus to scrape the new metrics.

---

## ✏️ Step 5 — Implement `AuditLogger.append()`

> [!IMPORTANT]
> **YOUR TASK** — Implement `AuditLogger.append(record)`. One JSON line per run, appended to `apo_audit.jsonl`.
>
> ```python
> with open(self.path, "a") as f:
>     f.write(json.dumps(record) + "\n")
> ```

> [!TIP]
> **PROVIDED** — `_build_record()` and `_write_audit()` helpers that assemble the full audit dict are already written. Your `append()` just writes what it receives.
> [!TIP]
> **🤖 Claude in production:** Raw JSONL is for machines. Claude would also write a natural-language incident summary alongside each record — one sentence describing what happened, why it was blocked or executed, and what the outcome was. That summary makes the audit log searchable by an operator asking "show me all incidents where the gate blocked a rollout last week."


Every autonomous decision — including no-ops, blocked proposals, and failed verifications — produces an audit record. JSONL format appends one JSON object per line, making the log crash-safe (a process kill mid-write corrupts at most the current line) and directly parseable by both humans and downstream tools. Each record captures the full context: what the agent saw, what it decided, what it executed, and whether it worked.

These records serve three distinct audiences: an on-call engineer pulling the postmortem, a compliance team auditing autonomous actions, and a future ML model training on `{metrics, action, outcome}` examples. JSONL is ideal for all three because it is human-readable with no special tooling, appendable without locking, and directly loadable by pandas or any log pipeline.

---

## 🔵 Step 6 — Run the full loop

**macOS / Linux:**

```bash
# Simulate mode — no cluster needed
python3 autonomous_agent_starter.py --simulate

# Against live cluster (requires Lab 1 cluster running and port-forwards open)
python3 autonomous_agent_starter.py

# Inject a fault first, then run to see the agent detect and remediate a real degradation
curl -X POST http://localhost:8080/toggle_fault
python3 autonomous_agent_starter.py
```

**Windows (PowerShell):**

```powershell
python autonomous_agent_starter.py --simulate

Invoke-WebRequest -Method POST http://localhost:8080/toggle_fault
python autonomous_agent_starter.py
```

---

## 🔵 Step 7
> [!TIP]
> **🤖 Claude in production:** You manually toggled the fault and triggered the agent here. In a live APO system, Claude watches the Prometheus alert stream and triggers the full loop automatically when an alert fires — no human initiates the run. The `--simulate` path you're running is exactly what Claude exercises during dry-run validation of a new gate configuration before it goes live.

---

## 🔵 Step 7 — Inspect the audit log

Each run writes one JSON line. The queries below extract the fields most useful for reviewing agent behavior and tracking MTTR (mean time to recovery).

**macOS / Linux:**

```bash
cat apo_audit.jsonl | python3 -m json.tool

python3 -c "
import json, sys
for line in open('apo_audit.jsonl'):
    r = json.loads(line)
    v = r.get('verification') or {}
    print(r['run_id'], r['outcome'], 'MTTR=', v.get('elapsed_seconds','n/a'))
"
```

**Windows:**

```cmd
type apo_audit.jsonl | python -m json.tool

python -c "import json; [print(r['run_id'], r['outcome']) for r in [json.loads(l) for l in open('apo_audit.jsonl')]]"
```
> [!TIP]
> **🤖 Claude in production:** Claude reads the audit log across runs — not just the most recent one — to surface patterns: which gate fires most often, which actions have the highest MTTR, whether a specific deployment recurs in incidents. Those patterns feed back into gate threshold tuning and action catalog updates.


---

## Success Criteria

**In-class:**
- [ ] `--simulate --dry-run` completes without errors and shows `[DRY RUN] Executed pod.rolling_restart`
- [ ] Gate blocks a 15% blast-radius proposal before the executor runs

**Take-home:**
- [ ] `--simulate` completes with `✅  Recovered in <N>s`
- [ ] `apo_audit.jsonl` contains a valid JSONL record with all fields
- [ ] MTTR < 120 seconds in simulate mode
- [ ] `--dry-run` skips kubectl but still writes an audit record

---

## Advanced: blast-radius gate test

Edit the `ActionProposal` in `run()` to set `blast_radius_fraction=0.15` and re-run with `--dry-run`. Confirm the gate blocks before the executor runs. This tests that the gate layer correctly rejects a proposal that is over the threshold, even when the confidence score is high.

---

## Files in this lab

```
lab2/
├── action_catalog.yaml            🟢 PROVIDED — do not modify
├── autonomous_agent_starter.py    ✏️ IN-CLASS (Steps 2–3) + TAKE-HOME (Steps 4–5)
├── solution/
│   └── autonomous_agent.py        🟢 PROVIDED — reference after you attempt the lab
└── README.md
```
