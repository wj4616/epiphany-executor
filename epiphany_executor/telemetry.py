"""Telemetry + resume brief + human-resolution / resume-from-halt UX (S-P5-telemetry, PC-07,
CV-03, IR-01/12).

Derives a health view from the ledger, produces a self-contained cold-start resume brief (so a
fresh/different effector can continue), and provides the halt-resolution surface: a structured
prompt per halt class (defect-ack INV-17, drift re-open/keep, irreversible-confirm INV-15,
waiver-ack), a uniform operator-ack mechanism, and a resume entry point that consumes the
recorded decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class HealthView:
    total: int = 0
    accepted: int = 0
    blocked: int = 0
    failed: int = 0
    in_flight: int = 0
    awaiting: int = 0
    verify_pass_rate: float | None = None
    back_edge_churn: int = 0
    coverage_pct: float | None = None
    est_remaining: int = 0
    # AX telemetry
    thinking_tiers: dict = field(default_factory=dict)
    resident_mode: str | None = None
    # CV-03 fan-out / spawn-cost telemetry
    max_concurrent_effectors: int = 0
    max_jury_width: int = 0
    speculative_count: int = 0


def health_view(ledger_entries: list[dict], *, total_steps: int = 0,
                coverage_pct: float | None = None, resident_mode: str | None = None,
                fanout: dict | None = None) -> HealthView:
    """Build the health view from ledger entries (lifecycle transitions, verdicts, back-updates,
    sentinel signals). Pure read over the append-only ledger."""
    hv = HealthView(total=total_steps, coverage_pct=coverage_pct, resident_mode=resident_mode)
    states: dict[str, str] = {}
    verify_pass = verify_total = 0
    for e in ledger_entries:
        kind = e.get("kind")
        if kind == "lifecycle-transition":
            states[e["node"]] = e.get("lifecycle_state")
        elif kind == "back-update-correcting-delta":
            hv.back_edge_churn += 1
        elif kind == "sentinel-regression-forward-delta":
            hv.back_edge_churn += 1
        verdict = e.get("verdict") or (e.get("dod_verdict") if isinstance(e.get("dod_verdict"), str) else None)
        if verdict in ("PASS", "FAIL"):
            verify_total += 1
            verify_pass += int(verdict == "PASS")
    for st in states.values():
        if st == "ACCEPTED":
            hv.accepted += 1
        elif st == "BLOCKED":
            hv.blocked += 1
        elif st == "FAILED":
            hv.failed += 1
        elif st == "IN_FLIGHT":
            hv.in_flight += 1
        elif st == "AWAITING":
            hv.awaiting += 1
    if verify_total:
        hv.verify_pass_rate = verify_pass / verify_total
    hv.est_remaining = max(0, total_steps - hv.accepted)
    if fanout:
        hv.max_concurrent_effectors = fanout.get("max_concurrent_effectors", 0)
        hv.max_jury_width = fanout.get("max_jury_width", 0)
        hv.speculative_count = fanout.get("speculative_count", 0)
    return hv


def resume_brief(plan_id: str, health: HealthView, next_steps: list[str],
                 graph_sha: str, session_dir: str) -> dict:
    """A self-contained cold-start brief: everything a fresh/different effector needs to continue
    (rehydration), independent of the prior effector's context."""
    return {
        "plan_id": plan_id,
        "graph_sha": graph_sha,
        "session_dir": session_dir,
        "progress": {"accepted": health.accepted, "total": health.total,
                     "blocked": health.blocked, "failed": health.failed},
        "next_steps": list(next_steps),
        "verify_pass_rate": health.verify_pass_rate,
        "coverage_pct": health.coverage_pct,
        "how_to_resume": f"goatcs-harness run --resume {session_dir}",
        "self_contained": True,
    }


class HaltClass(str, Enum):
    DEFECT_ACK = "defect-ack"               # INV-17 plan-declared gate/defect
    DRIFT_REOPEN_OR_KEEP = "drift"          # §5.6 plan drift on a started step
    IRREVERSIBLE_CONFIRM = "irreversible"   # INV-15 irreversible effect gate
    WAIVER_ACK = "waiver-ack"               # F-10 plan-caused coverage orphan
    BACKUPDATE_BUDGET = "backupdate-budget"  # INV-7 revision budget exhausted


_PROMPTS = {
    HaltClass.DEFECT_ACK: "Plan declares a BLOCKING gate/defect. Acknowledge & override, or abort?",
    HaltClass.DRIFT_REOPEN_OR_KEEP: "Plan content drifted on a started step. Re-open (re-verify) or keep?",
    HaltClass.IRREVERSIBLE_CONFIRM: "Next effect is externally-irreversible. Confirm to proceed, or skip?",
    HaltClass.WAIVER_ACK: "Requirement orphan is plan-caused. Acknowledge waiver (routes to epiphany-plan)?",
    HaltClass.BACKUPDATE_BUDGET: "Back-update revision budget exhausted. Raise budget, or halt?",
}
_CHOICES = {
    HaltClass.DEFECT_ACK: ["override-and-proceed", "abort"],
    HaltClass.DRIFT_REOPEN_OR_KEEP: ["reopen", "keep"],
    HaltClass.IRREVERSIBLE_CONFIRM: ["confirm", "skip-with-waiver", "halt"],
    HaltClass.WAIVER_ACK: ["ack-waiver", "abort"],
    HaltClass.BACKUPDATE_BUDGET: ["raise-budget", "halt"],
}


@dataclass
class HaltResolution:
    halt_class: HaltClass
    prompt: str
    choices: list[str]


def halt_resolution(halt_class: HaltClass) -> HaltResolution:
    """The structured operator prompt for a halt class (uniform ack mechanism)."""
    return HaltResolution(halt_class=halt_class, prompt=_PROMPTS[halt_class],
                          choices=list(_CHOICES[halt_class]))


@dataclass
class ResumedRun:
    resolved: bool
    decision: str
    resume_entry: str


def resume_from_halt(halt_class: HaltClass, operator_decision: str, session_dir: str) -> ResumedRun:
    """Consume a RECORDED operator decision and produce the resume entry point. A decision not in
    the halt class's legal choices is rejected (fail-closed)."""
    legal = _CHOICES[halt_class]
    if operator_decision not in legal:
        raise ValueError(f"illegal decision {operator_decision!r} for {halt_class.value}; "
                         f"choose one of {legal}")
    return ResumedRun(resolved=True, decision=operator_decision,
                      resume_entry=f"goatcs-harness run --resume {session_dir}")
