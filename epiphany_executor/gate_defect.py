"""Plan-declared gate / defect honoring (epiphany-executor S-P1-gate-defect, IC-P1g, INV-17).

Before executing, the executor reads plan-level ``gate_status``, ``blocking_defects``,
``structural_faults`` and per-step ``integration_checks.status``. If ``gate_status.verdict`` is
not PASS, there are open ``blocking_defects``, or a step's integration-check status is a BLOCKING
DEFECT, the executor produces a **HALT** decision and does NOT execute — the plan author already
flagged it un-ready (the real runs carry ``gate_status.verdict="FAIL"`` + DEFECT-1 = BLOCKING).
A clean plan (verdict PASS, no open defects, no blocking IC statuses) PROCEEDs.

The decision is consumed by the executor's start gate and surfaced through the telemetry
halt-resolution surface (S-P5-telemetry) for human resolution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _dc_field

# An integration-check status string is a BLOCKING DEFECT when it announces a DEFECT. The real
# emit uses several spellings: "DEFECT — ... BLOCKING ...", "DEFECT:partial_binding", etc.
# "OK", "OPEN (...)", "UNVERIFIED" are NOT blocking. We treat any status whose first token is
# DEFECT as a blocking defect (conservative / fail-closed, INV-10-aligned).
_DEFECT_RE = re.compile(r"^\s*DEFECT\b", re.IGNORECASE)


def _is_blocking_status(status: object) -> bool:
    return isinstance(status, str) and bool(_DEFECT_RE.match(status))


@dataclass
class GateDecision:
    decision: str                       # 'HALT' | 'PROCEED'
    reasons: list[str] = _dc_field(default_factory=list)
    blocking_steps: list[str] = _dc_field(default_factory=list)

    @property
    def halts(self) -> bool:
        return self.decision == "HALT"


def _iter_step_ics(step: dict):
    ic = step.get("integration_checks")
    if isinstance(ic, dict):
        yield ic
    elif isinstance(ic, list):
        for x in ic:
            if isinstance(x, dict):
                yield x


def evaluate_gate(plan: dict) -> GateDecision:
    """Produce the start-gate decision for a whole plan (INV-17).

    HALT if ANY of: ``gate_status.verdict`` != PASS; ``gate_status.gate`` == BLOCKING; any
    ``blocking_defects`` entry; any per-step ``integration_checks.status`` that is a BLOCKING
    DEFECT. Otherwise PROCEED. ``structural_faults`` are recorded as reasons (they accompany a
    BLOCKING gate in the real runs) but do not independently force a halt beyond the gate verdict."""
    reasons: list[str] = []
    blocking_steps: list[str] = []

    gate = plan.get("gate_status") or {}
    verdict = str(gate.get("verdict", "")).upper()
    gate_level = str(gate.get("gate", "")).upper()
    if verdict and verdict != "PASS":
        reasons.append(f"gate_status.verdict={verdict!r} (not PASS)")
    # A BLOCKING gate level only halts when the verdict did NOT pass. epiphany-plan marks its
    # coverage/structural gates as blocking-TYPE (``blocking: true``) even on PASS; a passed
    # blocking-type gate is not a halt (BD-4 reconciliation). Real blocking_defects below still
    # halt independently, so a genuine block is never masked.
    if gate_level == "BLOCKING" and verdict != "PASS":
        reasons.append("gate_status.gate=BLOCKING")

    defects = plan.get("blocking_defects") or []
    for d in defects:
        if isinstance(d, dict):
            reasons.append(f"blocking_defect {d.get('id', '?')}: {d.get('type', d.get('detail', ''))}")
        else:
            reasons.append(f"blocking_defect: {d}")

    faults = plan.get("structural_faults") or []
    for fault in faults:
        if isinstance(fault, dict):
            reasons.append(f"structural_fault {fault.get('fault_id', '?')}: {fault.get('type', '')}")

    for step in plan.get("steps", []):
        if not isinstance(step, dict):
            continue
        for ic in _iter_step_ics(step):
            if _is_blocking_status(ic.get("status")):
                sid = step.get("step_id", "?")
                blocking_steps.append(sid)
                reasons.append(f"step {sid} integration_check {ic.get('id', '?')} "
                               f"status={ic.get('status')!r} (BLOCKING DEFECT)")
                break

    decision = "HALT" if reasons else "PROCEED"
    return GateDecision(decision=decision, reasons=reasons, blocking_steps=sorted(set(blocking_steps)))
