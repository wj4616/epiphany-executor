"""Corpus ingest+execute validation (S-P6-validate, APU-019, R-019, INV-17) — BLOCKING GATE.

Runs the executor over the TUNING corpus: each plan must ingest (harness epiphany-plan importer),
gate-FAIL JSON runs must HALT correctly (INV-17), and clean plans must schedule end-to-end. An
ingest failure is recorded FAIL+open and routed to co-tuning (S-P1 back-edge) — NEVER silently
PASS. Markdown plans normalize first (executor MD normalizer) then ingest.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .corpus import CorpusPlan
from .gate_defect import evaluate_gate
from .scheduler import extract_contracts, schedule_waves


@dataclass
class PlanValidation:
    name: str
    kind: str
    ingested: bool = False
    gate_decision: str | None = None       # HALT | PROCEED
    scheduled: bool = False
    disposition: str = ""                   # end-to-end | correct-halt
    error: str | None = None
    routed_to_cotuning: bool = False        # True => FAIL+open back-edge to S-P1

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if self.disposition == "correct-halt":
            return self.gate_decision == "HALT"      # gate-FAIL must halt
        return self.ingested and self.scheduled       # end-to-end must ingest + schedule


def _load_plan_dict(plan: CorpusPlan):
    """Return the raw plan dict for gate/coverage + a loaded GraphSpec for scheduling."""
    import json

    from goatcs_harness.loader import load
    if plan.kind == "md":
        from .md_normalizer import normalize_plan_md
        raw, _lossy = normalize_plan_md(open(plan.path).read())
        # write normalized JSON to a temp file inside $HOME (ecryptfs: avoid /tmp EXDEV) then load
        import os
        import tempfile
        d = tempfile.mkdtemp(dir=os.path.expanduser("~/.cache"), prefix="exec-md-") \
            if os.path.isdir(os.path.expanduser("~/.cache")) else tempfile.mkdtemp()
        p = os.path.join(d, "plan.json")
        json.dump(raw, open(p, "w"))
        return raw, load(p)
    raw = json.load(open(plan.path))
    return raw, load(plan.path)


def validate_plan(plan: CorpusPlan) -> PlanValidation:
    v = PlanValidation(name=plan.name, kind=plan.kind, disposition=plan.disposition)
    try:
        raw, spec = _load_plan_dict(plan)
        v.ingested = True
    except Exception as ex:
        v.error = f"ingest failure: {type(ex).__name__}: {ex}"
        v.routed_to_cotuning = True            # FAIL+open back-edge to S-P1 (never silent PASS)
        return v
    gate = evaluate_gate(raw)
    v.gate_decision = gate.decision
    if gate.decision == "HALT":
        # correct behavior for a gate-FAIL plan (INV-17); for a clean plan a HALT is a real stop
        v.disposition = "correct-halt" if (raw.get("gate_status") or {}).get("verdict") != "PASS" \
            else v.disposition
        return v
    try:
        contracts = extract_contracts(spec)
        waves = schedule_waves(contracts, build_order=spec.raw.get("build_order"))
        v.scheduled = len(waves) >= 1 and sum(len(w.all_steps) for w in waves) == len(contracts)
    except Exception as ex:
        v.error = f"schedule failure: {type(ex).__name__}: {ex}"
        v.routed_to_cotuning = True
    return v


@dataclass
class ValidationReport:
    results: list[PlanValidation] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    @property
    def routed(self) -> list[str]:
        return [r.name for r in self.results if r.routed_to_cotuning]

    def to_dict(self) -> dict:
        return {"all_ok": self.all_ok, "routed_to_cotuning": self.routed,
                "results": [{"name": r.name, "kind": r.kind, "ingested": r.ingested,
                             "gate": r.gate_decision, "scheduled": r.scheduled,
                             "disposition": r.disposition, "ok": r.ok, "error": r.error}
                            for r in self.results]}


def validate_corpus(tuning_plans: list[CorpusPlan]) -> ValidationReport:
    return ValidationReport(results=[validate_plan(p) for p in tuning_plans])
