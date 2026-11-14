"""
Lab 1 — gate.py  (STARTER)
===========================
Implement the four confidence gates that guard every autonomous action.

Each gate is an AND condition — ALL four must pass before APO executes.
If any gate returns False, the action is blocked and routed to a human.

Gates
-----
1. Cost gate       — estimated action cost must be below the threshold
2. Blast radius    — fraction of pods affected must be below the max
3. Reversibility   — action must be undoable within the time limit
4. Time gate       — block during peak hours, month-end, deploy freeze

Thresholds (lab environment)
-----------------------------
  cost_per_hour_usd_max  : 500          (prod: 1000)
  blast_radius_max       : 0.10         (prod: 0.05)
  reversal_time_sec_max  : 600          (prod: 300)
  peak_hours             : 9–17 UTC     (approximate business hours)

Run (simulate mode — no k3d needed):
    python gate_starter.py --simulate

Run (real mode — requires Prometheus and k3d):
    python gate_starter.py
"""

from __future__ import annotations
import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ActionProposal:
    action_id: str
    deployment: str
    namespace: str
    estimated_cost_per_hour_usd: float
    blast_radius_fraction: float    # 0.0 – 1.0  (fraction of pods affected)
    reversal_time_seconds: int
    symptom_class: str
    confidence_score: float


@dataclass
class GateResult:
    approved: bool
    blocked_by: list[str] = field(default_factory=list)
    reasons: list[str]    = field(default_factory=list)

    def __str__(self) -> str:
        if self.approved:
            return "✅  GateResult(approved=True)"
        return f"🚫  GateResult(approved=False, blocked_by={self.blocked_by})"


# ── Lab configuration ─────────────────────────────────────────────────────────

@dataclass
class GateConfig:
    cost_per_hour_usd_max: float = 500.0    # lab threshold (prod: 1000)
    blast_radius_max: float      = 0.10     # lab threshold (prod: 0.05)
    reversal_time_sec_max: int   = 600      # lab threshold (prod: 300)
    peak_hours_utc: tuple        = (9, 17)  # block between 9am–5pm UTC


# ── TODO: Implement the GateOrchestrator ─────────────────────────────────────

class GateOrchestrator:
    """
    Evaluates all four gates for a given ActionProposal.

    All gates are AND conditions — if ANY gate fails, the action is blocked.
    The GateResult must include the name of every blocking gate so operators
    know why the action was held.
    """

    def __init__(self, config: GateConfig | None = None):
        self.config = config or GateConfig()

    def evaluate(self, proposal: ActionProposal) -> GateResult:
        """
        Run all four gates and return a GateResult.
        """
        gates = [
            ("cost_gate",          self._cost_gate),
            ("blast_radius_gate",  self._blast_radius_gate),
            ("reversibility_gate", self._reversibility_gate),
            ("time_gate",          self._time_gate),
        ]
        blocked_by, reasons = [], []
        for name, gate_fn in gates:
            passed, reason = gate_fn(proposal)
            if not passed:
                blocked_by.append(name)
                reasons.append(reason)
        return GateResult(approved=len(blocked_by) == 0, blocked_by=blocked_by, reasons=reasons)

    # ── Individual gates ──────────────────────────────────────────────────────

    def _cost_gate(self, proposal: ActionProposal) -> tuple[bool, str]:
        # TODO: Return (True, "") if proposal.estimated_cost_per_hour_usd
        #       is at or below self.config.cost_per_hour_usd_max.
        #       Otherwise return (False, "cost $X/hr exceeds limit $Y/hr").
        raise NotImplementedError("Implement _cost_gate()")

    def _blast_radius_gate(self, proposal: ActionProposal) -> tuple[bool, str]:
        # TODO: Return (True, "") if proposal.blast_radius_fraction
        #       is at or below self.config.blast_radius_max.
        #       Otherwise return (False, "blast radius X% exceeds limit Y%").
        raise NotImplementedError("Implement _blast_radius_gate()")

    def _reversibility_gate(self, proposal: ActionProposal) -> tuple[bool, str]:
        # TODO: Return (True, "") if proposal.reversal_time_seconds
        #       is at or below self.config.reversal_time_sec_max.
        #       Otherwise return (False, "reversal time Xs exceeds limit Ys").
        raise NotImplementedError("Implement _reversibility_gate()")

    def _time_gate(self, proposal: ActionProposal) -> tuple[bool, str]:
        # TODO: Block during peak hours.
        #       Get the current UTC hour with datetime.now(timezone.utc).hour
        #       Unpack self.config.peak_hours_utc as (start_h, end_h).
        #       If start_h <= current_h < end_h: return
        #           (False, "action blocked during peak hours (HH:00–HH:00 UTC), current hour=HH")
        #       Otherwise return (True, "").
        raise NotImplementedError("Implement _time_gate()")


# ── Test harness ──────────────────────────────────────────────────────────────

def _run_tests(config: GateConfig) -> None:
    orchestrator = GateOrchestrator(config)

    test_cases = [
        # (description, proposal, should_approve)
        (
            "Normal pod restart — should PASS all gates",
            ActionProposal(
                action_id="pod.rolling_restart",
                deployment="payment-service",
                namespace="default",
                estimated_cost_per_hour_usd=50.0,
                blast_radius_fraction=0.05,
                reversal_time_seconds=120,
                symptom_class="MEMORY_PRESSURE",
                confidence_score=0.84,
            ),
            True,
        ),
        (
            "Cost gate FAIL — $1200/hr exceeds $500 limit",
            ActionProposal(
                action_id="scale.horizontal_add",
                deployment="payment-service",
                namespace="default",
                estimated_cost_per_hour_usd=1200.0,
                blast_radius_fraction=0.05,
                reversal_time_seconds=120,
                symptom_class="CAPACITY_EXHAUSTION",
                confidence_score=0.78,
            ),
            False,
        ),
        (
            "Blast radius FAIL — 15% > 10% lab limit",
            ActionProposal(
                action_id="pod.rolling_restart",
                deployment="payment-service",
                namespace="default",
                estimated_cost_per_hour_usd=50.0,
                blast_radius_fraction=0.15,
                reversal_time_seconds=120,
                symptom_class="MEMORY_PRESSURE",
                confidence_score=0.84,
            ),
            False,
        ),
        (
            "Reversibility FAIL — 900s > 600s limit",
            ActionProposal(
                action_id="config.rollback",
                deployment="payment-service",
                namespace="default",
                estimated_cost_per_hour_usd=50.0,
                blast_radius_fraction=0.05,
                reversal_time_seconds=900,
                symptom_class="DEPLOYMENT_REGRESSION",
                confidence_score=0.76,
            ),
            False,
        ),
    ]

    print("\n" + "=" * 65)
    print("LAB 1 — GATE TESTS")
    print("=" * 65)

    passed = 0
    for desc, proposal, expected_approve in test_cases:
        try:
            result = orchestrator.evaluate(proposal)
            ok = result.approved == expected_approve
            status = "✅ PASS" if ok else "❌ FAIL"
            if ok:
                passed += 1
            print(f"\n{status}  {desc}")
            print(f"       approved={result.approved}  blocked_by={result.blocked_by}")
            if result.reasons:
                for r in result.reasons:
                    print(f"       reason: {r}")
        except NotImplementedError as e:
            print(f"\n⬜  NOT IMPLEMENTED — {desc}")
            print(f"   ({e})")

    print("\n" + "─" * 65)
    print(f"Results: {passed}/{len(test_cases)} tests passed")
    print()
    if passed == len(test_cases):
        print("All gates implemented correctly. Proceed to Step 5 in the lab README.")
    else:
        print("Some gates failed or are not implemented. Review the TODO comments above.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 1 — Gate Implementation")
    parser.add_argument("--simulate", action="store_true",
                        help="Run in simulate mode (no cluster needed)")
    args = parser.parse_args()

    if args.simulate:
        print("[SIMULATE MODE — running gate unit tests]")

    _run_tests(GateConfig())
