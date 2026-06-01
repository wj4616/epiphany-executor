"""Two-class Definition-of-Done verification (S-P3-dod, AX-04, INV-10, F-04/F-14).

DoD = acceptance_criteria ∪ integration_checks ∪ outputs (spec §2). Verification runs in a
FRESH verifier context that is given only {contract, integration_checks, artifacts/diff, ledger}
and STRUCTURALLY cannot see the effector's reasoning trace (concrete anti-self-grading;
verifier ≠ effector). Criteria are split into:
  - CLASS-OBJECTIVE — expressed as executable checks (command + expected exit/match), run by an
    injected `run_check`; the effector may NOT author its own check.
  - CLASS-SUBJECTIVE — deferred to an out-of-session reviewer / down-weighted (never auto-passed).
Ambiguous criteria default to the STRICTER class (objective → must be executably verified) and
are surfaced as low-confidence for human confirmation (F-14). Empty acceptance ⇒ BLOCKED
(INV-10). High-stakes steps escalate to an N-way jury (any-veto).

REUSE (INV-3): the executor does NOT implement a contract-conformance/routing gate of its own —
at runtime the verify_dod node's submission passes through the harness fidelity gate
(`goatcs_harness.session.submit` → `fidelity.validate_submission`). `conformance_check` here
calls the NAMED harness gate symbols (`fidelity.check_serializable`/`check_writes_present`) on
the verdict so the verdict is recorded through the harness gate, not a fork.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

# words that make a criterion machine-verifiable (objective)
_OBJECTIVE_MARKERS = (
    "pytest", "exit", "returns", "== ", "!=", "test", "passes", "fails", "compiles",
    "imports", "builds", "run ", "grep", "exists", "file ", "command", "output",
    "no error", "0 failures", "green", "schema", "validates", "matches", "count",
    "assert", "loads", "halts", "raise",
)
# words that make a criterion a human/aesthetic judgment (subjective)
_SUBJECTIVE_MARKERS = (
    "clean", "readable", "elegant", "appropriate", "well-", "well ", "good", "clear",
    "maintainable", "idiomatic", "reasonable", "sensible", "nice", "intuitive", "natural",
)


class CriterionClass(str, Enum):
    OBJECTIVE = "objective"
    SUBJECTIVE = "subjective"


class Decision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


def classify_criterion(text: str) -> tuple[CriterionClass, float]:
    """Return (class, confidence). Stricter-default: ambiguous → OBJECTIVE (must be executably
    verified) at LOW confidence (surfaced for human confirmation, F-14)."""
    low = str(text).lower()
    obj = any(m in low for m in _OBJECTIVE_MARKERS)
    subj = any(m in low for m in _SUBJECTIVE_MARKERS)
    if obj and not subj:
        return CriterionClass.OBJECTIVE, 0.9
    if subj and not obj:
        return CriterionClass.SUBJECTIVE, 0.9
    # ambiguous (both or neither) → stricter class, low confidence
    return CriterionClass.OBJECTIVE, 0.4


@dataclass
class DoD:
    objective: list[str] = field(default_factory=list)
    subjective: list[str] = field(default_factory=list)
    outputs: list = field(default_factory=list)
    low_confidence: list[str] = field(default_factory=list)   # for human confirmation (F-14)

    @property
    def verifiable(self) -> bool:
        return bool(self.objective) or bool(self.subjective) or bool(self.outputs)


def assemble_dod(contract: dict) -> DoD:
    """DoD = acceptance_criteria ∪ integration_checks ∪ outputs, criteria split by class."""
    dod_field = contract.get("dod") or {}
    acceptance = list(dod_field.get("acceptance_criteria") or [])
    integration = list(dod_field.get("integration_checks") or [])
    outputs = list(dod_field.get("outputs") or [])

    d = DoD(outputs=outputs)
    for crit in acceptance:
        text = crit if isinstance(crit, str) else str(crit)
        cls, conf = classify_criterion(text)
        (d.objective if cls is CriterionClass.OBJECTIVE else d.subjective).append(text)
        if conf < 0.5:
            d.low_confidence.append(text)
    # integration_checks are objective by construction (executable assertions).
    for ic in integration:
        d.objective.append(ic.get("assert", str(ic)) if isinstance(ic, dict) else str(ic))
    return d


@dataclass(frozen=True)
class VerifierContext:
    """The ONLY context a verifier sub-agent is given (AX-04 anti-self-grading). There is NO
    field for the effector's reasoning trace — it is structurally impossible to pass it."""
    contract: dict
    integration_checks: list
    artifacts: dict
    ledger: list = field(default_factory=list)

    @classmethod
    def for_step(cls, contract: dict, artifacts: dict, ledger: list | None = None) -> "VerifierContext":
        return cls(contract=contract,
                   integration_checks=list((contract.get("dod") or {}).get("integration_checks") or []),
                   artifacts=dict(artifacts or {}),
                   ledger=list(ledger or []))


@dataclass
class Verdict:
    decision: Decision
    objective_results: dict = field(default_factory=dict)   # criterion -> bool
    subjective_deferred: list = field(default_factory=list)
    low_confidence: list = field(default_factory=list)
    jury_votes: list = field(default_factory=list)          # per-juror Decision
    reason: str = ""


def _run_jury(dod: DoD, vctx: VerifierContext, run_check: Callable[[str, VerifierContext], bool],
              jury: int) -> tuple[list[Decision], dict]:
    """Run `jury` independent verifiers over the objective checks; any-veto (any FAIL ⇒ FAIL).
    Returns (per-juror decisions, merged objective_results)."""
    votes: list[Decision] = []
    merged: dict = {}
    for _ in range(max(1, jury)):
        ok = True
        for crit in dod.objective:
            passed = bool(run_check(crit, vctx))
            merged[crit] = merged.get(crit, True) and passed
            ok = ok and passed
        votes.append(Decision.PASS if ok else Decision.FAIL)
    return votes, merged


def verify_dod(contract: dict, artifacts: dict, *, run_check: Callable[[str, VerifierContext], bool],
               ledger: list | None = None, jury: int = 1) -> Verdict:
    """Verify a step's DoD. Empty acceptance+integration ⇒ BLOCKED (INV-10). Objective checks run
    in a fresh VerifierContext (no effector reasoning). Subjective criteria are deferred (never
    auto-passed). `jury>1` ⇒ any-veto. The verdict is contract-conformance-recorded through the
    NAMED harness fidelity-gate symbols at runtime (see module docstring)."""
    dod = assemble_dod(contract)
    if not dod.objective and not dod.subjective:
        return Verdict(decision=Decision.BLOCKED, reason="empty acceptance_criteria (INV-10 fail-closed)")

    vctx = VerifierContext.for_step(contract, artifacts, ledger)
    votes, results = _run_jury(dod, vctx, run_check, jury)
    # any-veto across the jury
    decision = Decision.PASS if all(v is Decision.PASS for v in votes) else Decision.FAIL
    # objective checks must all pass; subjective alone cannot make a step PASS (deferred).
    if dod.objective and not all(results.get(c, False) for c in dod.objective):
        decision = Decision.FAIL
    return Verdict(
        decision=decision,
        objective_results=results,
        subjective_deferred=list(dod.subjective),
        low_confidence=list(dod.low_confidence),
        jury_votes=votes,
        reason="" if decision is Decision.PASS else "objective DoD check(s) failed",
    )


def conformance_check(verdict_outputs: dict) -> list[str]:
    """Record the verdict through the NAMED harness fidelity-gate symbols (INV-3 reuse, not a
    fork): the verdict output must be JSON-serializable and present. Returns gate reasons
    ([] = ok). At runtime the full gate (`validate_submission`) runs in `session.submit`."""
    from goatcs_harness import fidelity  # named harness gate symbol — NOT reimplemented here
    reasons: list[str] = []
    ser = fidelity.check_serializable(verdict_outputs)
    if ser:
        reasons.extend(ser if isinstance(ser, list) else [str(ser)])
    if "dod_verdict" not in verdict_outputs:
        reasons.append("missing required write 'dod_verdict'")
    return reasons
