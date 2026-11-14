"""
Lab 1 — diagnostic_agent.py  (STARTER)
========================================
Implement the diagnostic agent that maps live Prometheus metrics to
a symptom class and computes a composite confidence score.

New in this file (vs gate_starter.py)
--------------------------------------
  detect_symptom_class()       — rules-based symptom classification
  ConfidenceScorer.compute()   — APO confidence formula C = 0.35S+0.25H+0.25R+0.15F
  PrometheusClient.query()     — live Prometheus queries  (optional — real mode only)
  MetricsReader.read()         — assembles the five-metric dict (optional — real mode only)

Run (simulate mode — no cluster needed):
    python3 diagnostic_agent_starter.py --simulate

Run (real mode — requires k3d + Prometheus):
    kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
    python3 diagnostic_agent_starter.py --prometheus-url http://localhost:9090
"""

from __future__ import annotations
import argparse
import sys
from datetime import datetime, timezone

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from gate_starter import GateOrchestrator, GateConfig, ActionProposal, GateResult


# ── PROVIDED: Simulated metrics ───────────────────────────────────────────────
# Used by --simulate so you can finish the lab without a live cluster.

SIMULATED_METRICS = {
    "memory_usage_ratio":      0.91,
    "error_rate_ratio":        0.038,
    "p99_latency_ms":          312,
    "p99_baseline_ms":         45,
    "restart_count_1h":        2,
    "last_scrape_age_seconds": 12,
}


# ── TODO: Implement detect_symptom_class ─────────────────────────────────────

def detect_symptom_class(metrics: dict[str, float]) -> str:
    """
    Map raw metric values to a named symptom class.

    Apply these rules in order and return the FIRST that matches:

    1. metrics["memory_usage_ratio"] > 0.85           → "MEMORY_PRESSURE"
    2. metrics["p99_latency_ms"] > 500
       AND metrics["error_rate_ratio"] > 0.05          → "DB_BOTTLENECK"
    3. metrics["error_rate_ratio"] > 0.10              → "DEPLOYMENT_REGRESSION"
    4. metrics["restart_count_1h"] > 5                 → "CAPACITY_EXHAUSTION"
    5. else                                             → "UNKNOWN"
    """
    # TODO: implement this function
    raise NotImplementedError("Implement detect_symptom_class()")


# ── TODO: Implement ConfidenceScorer ─────────────────────────────────────────

class ConfidenceScorer:
    """Computes the APO confidence formula: C = 0.35×S + 0.25×H + 0.25×R + 0.15×F"""

    # PROVIDED — historical win-rates for (symptom_class, action_id) pairs
    HISTORICAL_MATCH = {
        ("MEMORY_PRESSURE",       "pod.rolling_restart"):  0.78,
        ("DB_BOTTLENECK",         "db.connection_reset"):  0.65,
        ("DEPLOYMENT_REGRESSION", "config.rollback"):      0.91,
        ("CAPACITY_EXHAUSTION",   "scale.horizontal_add"): 0.72,
        ("DEPENDENCY_FAILURE",    "circuit.reset"):        0.60,
    }

    # PROVIDED — how reliable each action is in general
    REMEDIATION_CONFIDENCE = {
        "pod.rolling_restart":  0.90,
        "db.connection_reset":  0.75,
        "config.rollback":      0.95,
        "scale.horizontal_add": 0.80,
        "circuit.reset":        0.65,
    }

    def compute(
        self,
        metrics: dict[str, float],
        symptom_class: str,
        action_id: str,
    ) -> dict[str, float]:
        """
        Compute: C = 0.35×S + 0.25×H + 0.25×R + 0.15×F

        S — Signal Clarity  (use metrics["memory_usage_ratio"] as mem):
            mem > 0.90 → 0.95
            mem > 0.85 → 0.80
            mem > 0.75 → 0.60
            else       → 0.40

        H — Historical Match:
            Look up (symptom_class, action_id) in self.HISTORICAL_MATCH.
            Use 0.50 if the pair is not found.

        R — Remediation Confidence:
            Look up action_id in self.REMEDIATION_CONFIDENCE.
            Use 0.50 if the action_id is not found.

        F — Data Freshness  (use metrics["last_scrape_age_seconds"] as age):
            age < 30  → 0.95
            age < 60  → 0.80
            age < 120 → 0.65
            else      → 0.40

        Return {"S": S, "H": H, "R": R, "F": F, "C": C}
        where C = round(0.35*S + 0.25*H + 0.25*R + 0.15*F, 4).
        """
        # TODO: implement this method
        raise NotImplementedError("Implement ConfidenceScorer.compute()")


# ── TODO (OPTIONAL): Implement PrometheusClient ───────────────────────────────
# Skip if working in simulate mode — run() falls back to SIMULATED_METRICS.

class PrometheusClient:
    """Sends PromQL instant queries to a Prometheus HTTP API."""

    def __init__(self, base_url: str = "http://localhost:9090"):
        self.base_url = base_url.rstrip("/")

    def query(self, promql: str) -> float | None:
        """
        GET {self.base_url}/api/v1/query?query={promql}

        The response JSON structure:
            {"data": {"result": [{"value": [<timestamp>, "<value_string>"]}]}}

        Steps:
        1. Call requests.get(endpoint, params={"query": promql}, timeout=5)
        2. Call response.raise_for_status()
        3. Parse the JSON: data["data"]["result"]
        4. If result is empty, return None
        5. Return float(result[0]["value"][1])
        6. On any exception, return None

        OPTIONAL — implement for real-mode Prometheus integration.
        """
        # TODO (optional): implement this method
        raise NotImplementedError("Implement PrometheusClient.query() — or use --simulate")


# ── TODO (OPTIONAL): Implement MetricsReader ──────────────────────────────────
# Skip if working in simulate mode — run() falls back to SIMULATED_METRICS.

class MetricsReader:
    """Queries Prometheus for all five metrics and returns them as a dict."""

    def __init__(self, client: PrometheusClient, deployment: str, namespace: str):
        self.client     = client
        self.deployment = deployment
        self.namespace  = namespace

    def read(self) -> dict[str, float]:
        """
        Call self.client.query() five times (replace {d} with self.deployment)
        and return a dict with these exact keys:

            "memory_usage_ratio":
                process_memory_usage_ratio{deployment="{d}"}

            "error_rate_ratio":
                rate(http_requests_total{deployment="{d}",status_code=~"5.."}[2m])
                / rate(http_requests_total{deployment="{d}"}[2m])

            "p99_latency_ms":
                histogram_quantile(0.99,
                    rate(http_request_duration_seconds_bucket{deployment="{d}"}[2m])
                ) * 1000

            "restart_count_1h":
                increase(container_restart_total{deployment="{d}"}[1h])

            "last_scrape_age_seconds":
                time() - max(scrape_time{job="{d}"})

        Default to 0.0 when query() returns None.
        Set "p99_baseline_ms" to 45.0 (stored baseline — not queried from Prometheus).
        Round values to reasonable precision (e.g. round(x, 4)).

        OPTIONAL — implement for real-mode Prometheus integration.
        """
        # TODO (optional): implement this method
        raise NotImplementedError("Implement MetricsReader.read() — or use --simulate")


# ── PROVIDED ──────────────────────────────────────────────────────────────────

def symptom_to_action(symptom_class: str) -> str:
    return {
        "MEMORY_PRESSURE":       "pod.rolling_restart",
        "DB_BOTTLENECK":         "db.connection_reset",
        "DEPLOYMENT_REGRESSION": "config.rollback",
        "CAPACITY_EXHAUSTION":   "scale.horizontal_add",
    }.get(symptom_class, "escalate_human")


def autonomy_level(c: float) -> str:
    if c >= 0.90: return "L5 — act silently"
    if c >= 0.80: return "L4 — act + notify"
    if c >= 0.70: return "L3 — act + approval"
    if c >= 0.60: return "L2 — suggest"
    return          "L1 — escalate to human"


def run(prometheus_url: str, simulate: bool) -> None:
    deployment = "payment-service"
    namespace  = "default"

    print("\n" + "=" * 65)
    print("LAB 1 — DIAGNOSTIC AGENT")
    print("=" * 65)

    if simulate:
        print("\n[SIMULATE] MEMORY_PRESSURE scenario")
        metrics = SIMULATED_METRICS
    else:
        if not HAS_REQUESTS:
            print("ERROR: 'requests' not installed. Run: pip3 install requests")
            sys.exit(1)
        client = PrometheusClient(prometheus_url)
        reader = MetricsReader(client, deployment, namespace)
        try:
            metrics = reader.read()
        except NotImplementedError:
            print("NOTE: MetricsReader.read() not yet implemented — falling back to SIMULATED_METRICS")
            metrics = SIMULATED_METRICS

    print(f"\nMetrics for {deployment}:")
    for k, v in metrics.items():
        print(f"  {k:<35} {v}")

    try:
        symptom_class = detect_symptom_class(metrics)
    except NotImplementedError:
        print("\ndetect_symptom_class() not yet implemented.")
        return

    action_id = symptom_to_action(symptom_class)
    print(f"\nSymptom class:   {symptom_class}")
    print(f"Proposed action: {action_id}")

    scorer = ConfidenceScorer()
    try:
        scores = scorer.compute(metrics, symptom_class, action_id)
    except NotImplementedError:
        print("\nConfidenceScorer.compute() not yet implemented.")
        return

    print(f"\nConfidence scores:")
    print(f"  S: {scores['S']:.2f}  H: {scores['H']:.2f}  "
          f"R: {scores['R']:.2f}  F: {scores['F']:.2f}")
    print(f"  C = {scores['C']:.4f}  →  {autonomy_level(scores['C'])}")

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

    print(f"\n{gate_result}")
    for r in gate_result.reasons:
        print(f"  reason: {r}")

    print("\n" + "─" * 65)
    if gate_result.approved and scores["C"] >= 0.60:
        print(f"✅  DECISION: Execute {action_id} on {deployment}")
        print(f"   C={scores['C']:.4f} → {autonomy_level(scores['C'])}")
    elif not gate_result.approved:
        print(f"🚫  DECISION: Block — gate(s) failed: {gate_result.blocked_by}")
    else:
        print(f"🔺  DECISION: Escalate — C={scores['C']:.4f} below 0.60 threshold")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    args = parser.parse_args()
    run(args.prometheus_url, args.simulate)
