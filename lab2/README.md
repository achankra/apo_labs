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

Install pyyaml if needed:

```bash
pip3 install pyyaml
```

> **Windows:** use `pip install pyyaml`

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

**macOS / Linux:**

```bash
python3 autonomous_agent_starter.py --simulate --dry-run
# Expected: ✅  [DRY RUN] Executed pod.rolling_restart
```

**Windows:**

```cmd
python autonomous_agent_starter.py --simulate --dry-run
```

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

---

## 🔵 Step 6 — Run the full loop

**macOS / Linux:**

```bash
# Simulate mode — no cluster needed
python3 autonomous_agent_starter.py --simulate

# Against live cluster (requires Lab 1 cluster running and port-forwards open)
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

## 🔵 Step 7 — Inspect the audit log

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

Edit the `ActionProposal` in `run()` to set `blast_radius_fraction=0.15` and re-run with `--dry-run`. Confirm the gate blocks before the executor runs.

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
