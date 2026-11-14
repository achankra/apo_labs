"""
Lab 2 — autonomous_agent.py  (STARTER)
========================================
Extend the Lab 1 diagnostic agent into a fully autonomous remediation loop:
  detect → diagnose → gate → execute → verify → audit

New in this file (vs lab1)
---------------------------
  ActionExecutor.execute()           — run kubectl rollout restart via subprocess
  VerificationLoop.wait_for_recovery() — poll P90 latency until < 1.5× baseline
  AuditLogger.append()               — write one JSONL record per run

Run (simulate mode — no cluster needed):
    python3 autonomous_agent_starter.py --simulate

Run (dry-run — gate + executor logic, no kubectl):
    python3 autonomous_agent_starter.py --simulate --dry-run

Run (real mode — requires Lab 1 cluster + port-forwards):
    python3 autonomous_agent_starter.py
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

# Lab 1 modules live one directory up in lab1/
sys.path.insert(0, str(Path(__file__).parent.parent / "lab1"))

from gate_starter import GateOrchestrator, GateConfig, ActionProposal, GateResult
from diagnostic_agent_starter import (
    PrometheusClient, MetricsReader, ConfidenceScorer,
    detect_symptom_class, symptom_to_action, autonomy_level,
    SIMULATED_METRICS,
)

AUDIT_LOG_PATH = Path("apo_audit.jsonl")

# PROVIDED: post-restart metrics used by simulate mode in VerificationLoop
SIMULATED_POST_RESTART = {
    "memory_usage_ratio":      0.42,
    "error_rate_ratio":        0.004,
    "p99_latency_ms":          55,
    "p99_baseline_ms":         45,
    "restart_count_1h":        0,
    "last_scrape_age_seconds": 14,
}


# ── PROVIDED ──────────────────────────────────────────────────────────────────

def load_action_catalog(path: str = "action_catalog.yaml") -> dict[str, dict]:
    """Load the YAML action registry. Returns {} if the file is missing or pyyaml is not installed."""
    catalog_path = Path(__file__).parent / path
    if not catalog_path.exists():
        catalog_path = Path(path)
    if not catalog_path.exists() or not HAS_YAML:
        return {}
    with open(catalog_path) as f:
        raw = yaml.safe_load(f)
    return {a["action_id"]: a for a in raw.get("actions", [])}


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

        Steps:
        1. start = time.monotonic()
        2. executed_at = datetime.now(timezone.utc).isoformat()
        3. If self.simulate is True, return immediately — no kubectl:
               {"action_id": action_id, "deployment": deployment, "namespace": namespace,
                "executed_at": executed_at, "dry_run": False, "simulate": True,
                "success": True,
                "output": f"[SIMULATE] {action_id} on deployment/{deployment} -n {namespace}",
                "error": "", "duration_ms": 0}
        4. If self.dry_run is True, build cmd first, then return immediately — no kubectl:
               cmd = COMMANDS[action_id]   (see COMMANDS dict below)
               {"action_id": action_id, "deployment": deployment, "namespace": namespace,
                "executed_at": executed_at, "dry_run": True, "simulate": False,
                "success": True,
                "output": "[DRY RUN] " + " ".join(cmd),
                "error": "", "duration_ms": 0}
        5. cmd = COMMANDS[action_id]
        6. proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        7. duration_ms = int((time.monotonic() - start) * 1000)
        8. success = proc.returncode == 0
           Return dict using all fields in the return type above
           (output=proc.stdout, error=proc.stderr, dry_run=False, simulate=False).

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
    """Polls Prometheus until P90 latency drops below 1.5× the pre-action baseline."""

    def __init__(
        self,
        client: PrometheusClient | None,
        simulate: bool = False,
        poll_interval_seconds: int = 10,
        timeout_seconds: int = 120,
    ):
        self.client        = client
        self.simulate      = simulate
        self.poll_interval = poll_interval_seconds
        self.timeout       = timeout_seconds

    def wait_for_recovery(self, deployment: str, baseline_p90_ms: float) -> dict:
        """
        Poll until P90 < threshold, up to self.timeout seconds.

        Returns:
            {"recovered": bool, "final_p90_ms": float, "threshold_ms": float,
             "elapsed_seconds": float, "polls": int}

        Part A — Simulate mode (implement this first):
            if self.simulate:
                time.sleep(self.poll_interval)
                p90 = SIMULATED_POST_RESTART["p99_latency_ms"]
                threshold_ms = baseline_p90_ms * 1.5
                return {
                    "recovered": p90 < threshold_ms,
                    "final_p90_ms": p90,
                    "threshold_ms": threshold_ms,
                    "elapsed_seconds": float(self.poll_interval),
                    "polls": 1,
                }

        Part B — Real mode polling loop (implement after Part A passes):
            threshold_ms = baseline_p90_ms * 1.5
            start = time.monotonic()
            polls, p90 = 0, threshold_ms + 1
            PromQL to query:
                histogram_quantile(0.90,
                  rate(http_request_duration_seconds_bucket{deployment="{deployment}"}[1m])
                ) * 1000
            Loop: while time.monotonic() - start < self.timeout:
                p90 = self.client.query(promql)   # float ms
                polls += 1
                if p90 < threshold_ms: return {"recovered": True, ...}
                time.sleep(self.poll_interval)
            return {"recovered": False, "final_p90_ms": p90, ...}
        """
        # TODO: implement this method (Part A first, then Part B)
        raise NotImplementedError("Implement VerificationLoop.wait_for_recovery()")


# ── TODO: Implement AuditLogger ───────────────────────────────────────────────

class AuditLogger:
    """Appends one JSONL record per run to the audit log file."""

    def __init__(self, path: Path = AUDIT_LOG_PATH):
        self.path = path

    def append(self, record: dict) -> None:
        """
        Append `record` as a single JSON line to self.path.

        Two lines:
            with open(self.path, "a") as f:
                f.write(json.dumps(record) + "\\n")

        "a" mode appends without overwriting previous runs.
        Each run becomes a separate line (JSONL format).
        """
        # TODO: implement this method (two lines)
        raise NotImplementedError("Implement AuditLogger.append()")


# ── PROVIDED: orchestration ───────────────────────────────────────────────────

def _build_record(run_id, deployment, namespace, symptom_class, action_id,
                  scores, gate_result, exec_result, verify_result, outcome):
    return {
        "run_id":          run_id,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "deployment":      deployment,
        "namespace":       namespace,
        "symptom_class":   symptom_class,
        "action_id":       action_id,
        "confidence":      scores,
        "gate_approved":   gate_result.approved,
        "gate_blocked_by": gate_result.blocked_by,
        "execution":       exec_result,
        "verification":    verify_result,
        "outcome":         outcome,
    }


def run(prometheus_url: str, simulate: bool, dry_run: bool) -> None:
    deployment = "payment-service"
    namespace  = "default"
    run_id     = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("\n" + "=" * 65)
    print("LAB 2 — AUTONOMOUS REMEDIATION AGENT")
    print("=" * 65)
    print(f"Run ID: {run_id}")

    catalog = load_action_catalog()
    print(f"\nAction catalog: {len(catalog)} actions loaded")

    if simulate:
        print("\n[SIMULATE] MEMORY_PRESSURE scenario")
        metrics = SIMULATED_METRICS
        client  = None
    else:
        if not HAS_REQUESTS:
            print("ERROR: requests not installed. Run: pip3 install requests")
            sys.exit(1)
        client  = PrometheusClient(prometheus_url)
        reader  = MetricsReader(client, deployment, namespace)
        try:
            metrics = reader.read()
        except NotImplementedError:
            print("NOTE: MetricsReader.read() not yet implemented — falling back to SIMULATED_METRICS")
            metrics = SIMULATED_METRICS
            client  = None

    print(f"\nMetrics:")
    for k, v in metrics.items():
        print(f"  {k:<35} {v}")

    try:
        symptom_class = detect_symptom_class(metrics)
    except NotImplementedError:
        print("\ndetect_symptom_class() not yet implemented (complete Lab 1 first).")
        return

    action_id = symptom_to_action(symptom_class)
    scorer    = ConfidenceScorer()
    try:
        scores = scorer.compute(metrics, symptom_class, action_id)
    except NotImplementedError:
        print("\nConfidenceScorer.compute() not yet implemented (complete Lab 1 first).")
        return

    print(f"\nDiagnosis:  {symptom_class}  →  {action_id}")
    print(f"Confidence: C={scores['C']:.4f}  ({autonomy_level(scores['C'])})")

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

    logger = AuditLogger()

    if not gate_result.approved:
        print("\n🚫  BLOCKED")
        try:
            logger.append(_build_record(run_id, deployment, namespace, symptom_class,
                                        action_id, scores, gate_result,
                                        None, None, "GATE_BLOCKED"))
        except NotImplementedError:
            pass
        return

    if scores["C"] < 0.60:
        print(f"\n🔺  ESCALATE — C={scores['C']:.4f}")
        try:
            logger.append(_build_record(run_id, deployment, namespace, symptom_class,
                                        action_id, scores, gate_result,
                                        None, None, "ESCALATED"))
        except NotImplementedError:
            pass
        return

    executor = ActionExecutor(dry_run=dry_run, simulate=simulate)
    try:
        exec_result = executor.execute(action_id, deployment, namespace)
    except NotImplementedError:
        print("\nActionExecutor.execute() not yet implemented.")
        return

    label = "[DRY RUN] " if dry_run else ("[SIMULATE] " if simulate else "")
    if exec_result["success"]:
        print(f"\n✅  {label}Executed {action_id} in {exec_result['duration_ms']}ms")
        print(f"   {exec_result['output']}")
    else:
        print(f"\n❌  Execution FAILED: {exec_result['error']}")
        try:
            logger.append(_build_record(run_id, deployment, namespace, symptom_class,
                                        action_id, scores, gate_result,
                                        exec_result, None, "EXECUTION_FAILED"))
        except NotImplementedError:
            pass
        return

    baseline_p90 = metrics.get("p99_baseline_ms", 50.0)
    verifier     = VerificationLoop(client=client, simulate=simulate)
    print(f"\nWaiting for P90 < {baseline_p90 * 1.5:.0f}ms (1.5× baseline {baseline_p90:.0f}ms) …")

    try:
        verify_result = verifier.wait_for_recovery(deployment, baseline_p90)
    except NotImplementedError:
        print("VerificationLoop.wait_for_recovery() not yet implemented.")
        return

    if verify_result["recovered"]:
        print(f"✅  Recovered in {verify_result['elapsed_seconds']:.0f}s "
              f"— P90={verify_result['final_p90_ms']:.0f}ms")
        outcome = "RECOVERED"
    else:
        print(f"⚠️  NOT recovered after {verifier.timeout}s")
        outcome = "ESCALATED"

    try:
        logger.append(_build_record(run_id, deployment, namespace, symptom_class,
                                    action_id, scores, gate_result,
                                    exec_result, verify_result, outcome))
        print(f"\nAudit written to {AUDIT_LOG_PATH}")
    except NotImplementedError:
        print("\nAuditLogger.append() not yet implemented.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 2 — Autonomous Remediation Agent")
    parser.add_argument("--simulate",       action="store_true",
                        help="Run in simulate mode (no cluster needed)")
    parser.add_argument("--dry-run",        action="store_true",
                        help="Build and log kubectl command without executing it")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    args = parser.parse_args()
    run(args.prometheus_url, args.simulate, args.dry_run)
