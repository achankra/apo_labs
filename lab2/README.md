# Lab 2 — Single-Agent Autonomous Remediation

**Duration:** 45 minutes total · 20 min in-class · 25 min take-home  
**Builds on:** Lab 1 (gate.py + diagnostic_agent.py)  
**Goal:** Extend the diagnostic agent into a fully autonomous remediation loop: detect → diagnose → gate → **execute → verify → audit**

---

## Prerequisites

Lab 1 must be complete (gate + diagnostic agent both pass in simulate mode).  
The Lab 1 cluster must be running, or `setup.sh` will start it for you.

---

## Step 1 — Start the lab environment

```bash
chmod +x setup.sh
./setup.sh
```

This reuses the Lab 1 cluster. If Lab 1's cluster is not running, `setup.sh` starts it. If port-forwards have died, it restores them. Takes under 30 seconds if the cluster is already up.

---

## What you'll add in this lab

| Component | Status | Timing | What it does |
|---|---|---|---|
| `load_action_catalog()` | ✏️ **YOUR TASK** | In-class | Reads and parses the YAML action registry |
| `ActionExecutor.execute()` | ✏️ **YOUR TASK** | In-class | Runs `kubectl rollout restart` via subprocess |
| `VerificationLoop.wait_for_recovery()` | ✏️ **YOUR TASK** | Take-home | Polls P90 latency until it drops to 1.5× baseline |
| `AuditLogger.append()` | ✏️ **YOUR TASK** | Take-home | Appends a full JSONL record per run |
| `action_catalog.yaml` | 🟢 **PROVIDED** | — | Registry of approved actions with risk metadata |
| `run()` orchestration | 🟢 **PROVIDED** | — | Chains all components in order |

---

---

# 🏫 IN-CLASS — 20 minutes

---

## Step 2 — Inspect the action catalog *(read only)*

Open `action_catalog.yaml`. Each action specifies `risk_class`, `blast_radius_max`, `reversal_time_seconds`, `required_confidence`, `max_executions_per_hour`, `cooldown_seconds`, and `symptom_classes`. This is what APO agents consult before proposing an action — it is the boundary of what the agent is authorized to do.

> **🤖 Claude in production:** Claude doesn't read a static YAML file — it queries a live action catalog service via API. When no approved action fits a novel symptom, Claude can draft a new candidate action and submit it for human review before it enters the catalog.

---

## Step 3 — Implement `load_action_catalog()` ✏️

Open `autonomous_agent_starter.py`. Implement `load_action_catalog(path)`:

1. Open the YAML file at `path`
2. Parse with `yaml.safe_load`
3. Return a dict keyed by `action_id`

```python
import yaml
with open(path) as f:
    raw = yaml.safe_load(f)
return {a["action_id"]: a for a in raw["actions"]}
```

`yaml.safe_load` is the secure parser variant — it cannot execute arbitrary Python embedded in the YAML.

---

## Step 4 — Implement `ActionExecutor.execute()` ✏️

Implement `ActionExecutor.execute(action_id, deployment, namespace)`:

1. Map `action_id` to a `kubectl` command
2. Run via `subprocess.run` with a 30 s timeout
3. Return a dict with `success`, `output`, `error`, `duration_ms`, and `dry_run`/`simulate` flags

For `pod.rolling_restart`:
```bash
kubectl rollout restart deployment/{deployment} -n {namespace}
```

> `simulate` and `dry_run` flags are already wired — in simulate mode the executor returns a canned success dict without calling kubectl.

The `dry_run` flag lets you test the full decision path in a live environment without restarting any pods — useful for validating gate logic during an incident.

> **🤖 Claude in production:** Claude selects the execution method based on the target — a Kubernetes workload gets kubectl, a VM-based service gets an Ansible playbook, a managed cloud service gets an API call. The `ActionExecutor` abstraction maps to this.

Test:

```bash
python3 autonomous_agent_starter.py --simulate --dry-run
# Expected: ✅  [DRY RUN] Executed pod.rolling_restart
```

---

---

# 🏠 TAKE-HOME — 25 minutes

---

## Step 5 — Implement `VerificationLoop.wait_for_recovery()` ✏️

Implement the recovery polling loop.

**Success criterion:** P90 latency drops below 1.5× the pre-action baseline within 120 seconds.

PromQL to poll P90:
```
histogram_quantile(0.90,
  rate(http_request_duration_seconds_bucket{deployment="payment-service"}[1m])
) * 1000
```

Polling pseudocode:
```python
threshold_ms = baseline_p90 * 1.5
start = time.monotonic()
while elapsed < timeout:
    p90 = query_prometheus(...)
    if p90 < threshold_ms:
        return {"recovered": True, "elapsed_seconds": elapsed, ...}
    time.sleep(poll_interval)
return {"recovered": False, ...}
```

> In simulate mode, `wait_for_recovery()` already returns `recovered: True` after one poll interval. Implement the real-mode polling path.

> **🤖 Claude in production:** Claude would derive the 1.5× threshold dynamically from the deployment's historical p90 distribution — tight enough to catch a failed recovery, not so tight it false-positives on normal traffic jitter.

---

## Step 6 — Implement `AuditLogger.append()` ✏️

Implement `AuditLogger.append(record)`. One JSON line per run, appended to `apo_audit.jsonl`.

```python
with open(self.path, "a") as f:
    f.write(json.dumps(record) + "\n")
```

> `_build_record()` and `_write_audit()` helpers that assemble the full audit dict are already written.

Every autonomous decision — including no-ops, blocked proposals, and failed verifications — produces an audit record. JSONL is crash-safe (a kill mid-write corrupts at most the current line), directly parseable by both humans and downstream tools, and usable as a training dataset for future models.

---

## Step 7 — Run the full loop

```bash
# Simulate mode — no cluster needed
python3 autonomous_agent_starter.py --simulate

# Against live cluster
python3 autonomous_agent_starter.py

# Inject a fault first, then run
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

## Step 8 — Inspect the audit log

```bash
cat apo_audit.jsonl | python3 -m json.tool

python3 -c "
import json
for line in open('apo_audit.jsonl'):
    r = json.loads(line)
    v = r.get('verification') or {}
    print(r['run_id'], r['outcome'], 'MTTR=', v.get('elapsed_seconds','n/a'))
"
```

---

## Blast-radius gate test

Set `blast_radius_fraction=0.15` on the `ActionProposal` in `run()` and re-run with `--dry-run`. Confirm the gate blocks before the executor runs.

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

## Cleanup

```bash
./teardown.sh               # stops port-forwards and load generator
../lab1/teardown.sh         # deletes the cluster (run only after all labs are done)
```

---

## Files in this lab

```
lab2/
├── action_catalog.yaml            🟢 PROVIDED — do not modify
├── setup.sh                       🟢 PROVIDED — run once at the start
├── teardown.sh                    🟢 PROVIDED — run when done
├── autonomous_agent_starter.py    ✏️ IN-CLASS (Steps 3–4) + TAKE-HOME (Steps 5–6)
├── solution/
│   └── autonomous_agent.py        🟢 Reference — look after you attempt the lab
└── README.md
```
