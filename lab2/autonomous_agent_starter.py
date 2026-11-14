"""
Lab 2 — autonomous_agent.py  (STARTER)
========================================
Extend Lab 1 to build a fully autonomous single-agent remediation loop:
  detect → diagnose → gate → execute → verify → audit

New in Lab 2 vs Lab 1
----------------------
1. Load action catalog from action_catalog.yaml
2. Execute the approved action via kubectl rollout restart
3. Verification loop — poll P90 latency until it drops to 1.5× baseline
4. JSONL audit log — append one record per run (full telemetry → score → gate → outcome)

Run (simulate mode — no cluster needed):
    python autonomous_agent_starter.py --simulate

Run (real mode — requires k3d + Prometheus):
    kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
    python autonomous_agent_starter.py --prometheus-url http://localhost:9090
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Reuse Lab 1 components (adjust path if running from lab2/ directory)
sys.path.insert(0, str(Path(__file__).parent.parent / "lab1"))
sys.path.insert(0, str(Path(__file__).parent.parent / "lab1" / "solution"))

try:
    from gate import GateOrchestrator, GateConfig, ActionProposal, GateResult
except ImportError:
    from solution.gate import GateOrchestrator, GateConfig, ActionProposal, GateResult  # type: ignore

try:
    from diagnostic_agent import (
        PrometheusClient, MetricsReader, ConfidenceScorer,
        detect_symptom_class, symptom_to_action, autonomy_level,
        SIMULATED_METRICS,
    )
except ImportError:
    from solution.diagnostic_agent import (           # type: ignore
        PrometheusClient, MetricsReader, ConfidenceScorer,
        detect_symptom_class, symptom_to_action, autonomy_level,
        SIMULATED_METRICS,
    )


AUDIT_LOG_PATH = Path("apo_audit.jsonl")


# ── Simulated post-restart metrics ───────────────────────────────────────────
# Returned by simulate_verification() after a fake restart succeeds.
SIMULATED_POST_RESTART = {
    "memory_usage_ratio": 0.42,
    "error_rate_ratio": 0.004,
    "p99_latency_ms": 55,
    "p99_baseline_ms": 45,
    "restart_count_1h": 0,
    "last_scrape_age_seconds": 14,
}


# ── TODO: Load action catalog ─────────────────────────────────────────────────

def load_action_catalog(path: str = "action_catalog.yaml") -> dict[str, dict]:
    """
    Load action_catalog.yaml and return a dict keyed by action_id.

    Hint:
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f)
        return {a["action_id"]: a for a in raw["actions"]}

    Returns {} if the file cannot be read or yaml is not installed.
    """
    # TODO: implement this function
    raise NotImplementedError("Implement load_action_catalog()")


# ── TODO: Implement ActionExecutor ───────────────────────────────────────────

class ActionExecutor:
    """Executes approved remediation actions via kubectl."""

    def __init__(self, dry_run: bool = False, simulate: bool = False):
        self.dry_run  = dry_run
        self.simulate = simulate

    def execute(self, action_id: str, deployment: str, namespace: str) -> dict:
        """
        Execute the action and return a result dict:
            {
              "action_id":    str,
              "deployment":   str,
              "namespace":    str,
              "executed_at":  ISO-8601 string,
              "dry_run":      bool,
              "simulate":     bool,
              "success":      bool,
              "output":       str,   # stdout / simulated message
              "error":        str,   # stderr / "" on success
              "duration_ms":  int,
            }

        For pod.rolling_restart: run
            kubectl rollout restart deployment/{deployment} -n {namespace}

        Steps:
        1. Record start time
        2. If self.simulate: return success with fake output, skip kubectl
        3. If self.dry_run:  return success with "[DRY RUN]" output, skip kubectl
        4. Build the command for the action_id (see COMMANDS below)
        5. Run with subprocess.run(..., capture_output=True, text=True, timeout=30)
        6. Record end time
        7. Return result dict

        COMMANDS = {
            "pod.rolling_restart": [
                "kubectl", "rollout", "restart",
                f"deployment/{deployment}", "-n", namespace
            ],
            "config.rollback": [
                "kubectl", "rollout", "undo",
                f"deployment/{deployment}", "-n", namespace
            ],
        }
        """
        # TODO: implement this method
        raise NotImplementedError("Implement ActionExecutor.execute()")


# ── TODO: Implement VerificationLoop ─────────────────────────────────────────

class VerificationLoop:
    """
    Polls Prometheus after an action to verify recovery.

    Success criterion (from Lab 2 slide):
        P90 latency drops to below 1.5× the pre-action baseline
        WITHIN the timeout window (default: 120 seconds).
    """

    def __init__(
        self,
        client: PrometheusClient | None,
        simulate: bool = False,
        poll_interval_seconds: int = 10,
        timeout_seconds: int = 120,
    ):
        self.client          = client
        self.simulate        = simulate
        self.poll_interval   = poll_interval_seconds
        self.timeout         = timeout_seconds

    def wait_for_recovery(
        self,
        deployment: str,
        baseline_p90_ms: float,
    ) -> dict:
        """
        Poll until P90 latency < 1.5× baseline OR timeout.

        Returns:
            {
              "recovered":           bool,
              "final_p90_ms":        float,
              "threshold_ms":        float,   # 1.5 × baseline
              "elapsed_seconds":     float,
              "polls":               int,
            }

        Polling logic:
        1. Record start time
        2. Loop until elapsed >= timeout_seconds:
           a. If simulate: use SIMULATED_POST_RESTART["p99_latency_ms"] as p90
           b. Else: query Prometheus for
              histogram_quantile(0.90,
                rate(http_request_duration_seconds_bucket{deployment="..."}[1m])
              ) * 1000
           c. If p90 < threshold: return recovered=True immediately
           d. Sleep poll_interval seconds
        3. If loop exits without recovery: return recovered=False with final values

        Hint: threshold_ms = baseline_p90_ms * 1.5
        """
        # TODO: implement this method
        raise NotImplementedError("Implement VerificationLoop.wait_for_recovery()")


# ── TODO: Implement AuditLogger ───────────────────────────────────────────────

class AuditLogger:
    """
    Appends a JSONL record to apo_audit.jsonl for every agent run.

    One line per run. Each line is a JSON object with:
      timestamp, deployment, namespace, symptom_class, action_id,
      confidence (C,S,H,R,F), gate_approved, gate_blocked_by,
      execution (success, duration_ms, dry_run), verification (recovered, elapsed_s),
      outcome ("RECOVERED" | "ESCALATED" | "GATE_BLOCKED" | "EXECUTION_FAILED")
    """

    def __init__(self, path: Path = AUDIT_LOG_PATH):
        self.path = path

    def append(self, record: dict) -> None:
        """
        Append `record` as a single JSON line to self.path.

        Hint:
            with open(self.path, "a") as f:
                f.write(json.dumps(record) + "\n")
        """
        # TODO: implement this method
        raise NotImplementedError("Implement AuditLogger.append()")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(prometheus_url: str, simulate: bool, dry_run: bool) -> None:
    deployment = "payment-service"
    namespace  = "default"
    run_id     = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("\n" + "=" * 65)
    print("LAB 2 — AUTONOMOUS REMEDIATION AGENT")
    print("=" * 65)
    print(f"Run ID: {run_id}")

    # ── 1. Load action catalog ────────────────────────────────────────────────
    try:
        catalog = load_action_catalog()
        print(f"\nAction catalog loaded ({len(catalog)} actions)")
    except (NotImplementedError, Exception) as e:
        print(f"\nAction catalog not loaded: {e} — continuing with defaults")
        catalog = {}

    # ── 2. Read metrics ───────────────────────────────────────────────────────
    if simulate:
        print("\n[SIMULATE] Using pre-canned MEMORY_PRESSURE metrics")
        metrics = SIMULATED_METRICS
        client  = None
    else:
        if not HAS_REQUESTS:
            print("ERROR: requests not installed")
            sys.exit(1)
        client  = PrometheusClient(prometheus_url)
        reader  = MetricsReader(client, deployment, namespace)
        metrics = reader.read()

    print(f"\nMetrics snapshot:")
    for k, v in metrics.items():
        print(f"  {k:<35} {v}")

    # ── 3. Diagnose ───────────────────────────────────────────────────────────
    symptom_class = detect_symptom_class(metrics)
    action_id     = symptom_to_action(symptom_class)

    scorer  = ConfidenceScorer()
    scores  = scorer.compute(metrics, symptom_class, action_id)

    print(f"\nDiagnosis:  {symptom_class}  →  {action_id}")
    print(f"Confidence: C={scores['C']:.4f}  S={scores['S']:.2f}  "
          f"H={scores['H']:.2f}  R={scores['R']:.2f}  F={scores['F']:.2f}")
    print(f"Autonomy:   {autonomy_level(scores['C'])}")

    # ── 4. Gate evaluation ────────────────────────────────────────────────────
    proposal = ActionProposal(
        action_id=action_id,
        deployment=deployment,
        namespace=namespace,
        estimated_cost_per_hour_usd=50.0,
        blast_radius_fraction=0.05,
        reversal_time_seconds=120,
        symptom_class=symptom_class,
        confidence_score=scores["C"],
    )

    orchestrator = GateOrchestrator(GateConfig())
    gate_result  = orchestrator.evaluate(proposal)

    print(f"\nGate: {gate_result}")
    for r in gate_result.reasons:
        print(f"  → {r}")

    if not gate_result.approved:
        print("\n🚫  BLOCKED — writing audit record and exiting")
        _write_audit(run_id, deployment, namespace, symptom_class, action_id,
                     scores, gate_result, None, None, "GATE_BLOCKED")
        return

    if scores["C"] < 0.60:
        print(f"\n🔺  ESCALATE — confidence {scores['C']:.4f} below 0.60")
        _write_audit(run_id, deployment, namespace, symptom_class, action_id,
                     scores, gate_result, None, None, "ESCALATED")
        return

    # ── 5. Execute ────────────────────────────────────────────────────────────
    executor = ActionExecutor(dry_run=dry_run, simulate=simulate)
    try:
        exec_result = executor.execute(action_id, deployment, namespace)
    except NotImplementedError:
        print("\nActionExecutor.execute() not yet implemented — skipping execution")
        return

    label = "[DRY RUN] " if dry_run else ("[SIMULATE] " if simulate else "")
    if exec_result["success"]:
        print(f"\n✅  {label}Executed {action_id} in {exec_result['duration_ms']}ms")
        print(f"   {exec_result['output'][:120]}")
    else:
        print(f"\n❌  Execution FAILED: {exec_result['error']}")
        _write_audit(run_id, deployment, namespace, symptom_class, action_id,
                     scores, gate_result, exec_result, None, "EXECUTION_FAILED")
        return

    # ── 6. Verify recovery ────────────────────────────────────────────────────
    baseline_p90 = metrics.get("p99_baseline_ms", 50.0)
    verifier     = VerificationLoop(client=client, simulate=simulate)

    print(f"\nWaiting for P90 < {baseline_p90 * 1.5:.0f}ms "
          f"(1.5× baseline {baseline_p90:.0f}ms) …")

    try:
        verify_result = verifier.wait_for_recovery(deployment, baseline_p90)
    except NotImplementedError:
        print("VerificationLoop.wait_for_recovery() not yet implemented")
        return

    if verify_result["recovered"]:
        print(f"✅  Recovered in {verify_result['elapsed_seconds']:.0f}s — "
              f"P90={verify_result['final_p90_ms']:.0f}ms "
              f"(threshold {verify_result['threshold_ms']:.0f}ms)")
        outcome = "RECOVERED"
    else:
        print(f"⚠️  Did NOT recover within {verifier.timeout}s — "
              f"P90={verify_result['final_p90_ms']:.0f}ms still above "
              f"{verify_result['threshold_ms']:.0f}ms")
        outcome = "ESCALATED"

    # ── 7. Audit ──────────────────────────────────────────────────────────────
    _write_audit(run_id, deployment, namespace, symptom_class, action_id,
                 scores, gate_result, exec_result, verify_result, outcome)
    print(f"\nAudit record written to {AUDIT_LOG_PATH}")
    print()


def _write_audit(
    run_id, deployment, namespace, symptom_class, action_id,
    scores, gate_result, exec_result, verify_result, outcome,
):
    logger = AuditLogger()
    record = {
        "run_id":       run_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "deployment":   deployment,
        "namespace":    namespace,
        "symptom_class": symptom_class,
        "action_id":    action_id,
        "confidence":   scores,
        "gate_approved": gate_result.approved,
        "gate_blocked_by": gate_result.blocked_by,
        "execution":    exec_result,
        "verification": verify_result,
        "outcome":      outcome,
    }
    try:
        logger.append(record)
    except NotImplementedError:
        print("(AuditLogger.append() not yet implemented — skipping audit)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 2 — Autonomous Agent")
    parser.add_argument("--simulate",   action="store_true",
                        help="Use simulated metrics and fake kubectl calls")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Go through gate + execution path but don't run kubectl")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    args = parser.parse_args()
    run(args.prometheus_url, args.simulate, args.dry_run)
