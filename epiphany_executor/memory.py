"""Cross-run Memory flywheel (S-P8-learn, AX-07, INV-12).

Distills each run's ledger into persistent, **versioned, revocable, advisory** priors:
failure-mode signatures, effect-misclassification corrections, thinking-budget calibration
(predicted vs actual), and plan-shape priors (antichain widths, conflict-prone edge_classes).
S-P2-context primes the scheduler/allocator/verifier with these priors.

Binding (AX-07): priors are ADVISORY — they may raise a thinking tier or hint scheduling, but
NEVER relax a gate or skip a check. A run with empty OR wrong memory is still correct
(`apply_memory_priors` is raise-only and a no-op on empty). Each prior is versioned + attributed
in the ledger so a bad prior is revocable. CV-07 acceptance: a flywheel entry measurably alters a
subsequent run's schedule or thinking-budget (else the prior is labeled advisory-only).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class Prior:
    key: str
    kind: str                 # failure-signature | effect-correction | budget-calibration | plan-shape
    value: object
    version: int = 1
    source_run: str = ""
    revoked: bool = False


@dataclass
class PriorStore:
    """A versioned, revocable prior store (JSON-backed). Advisory only."""
    path: str
    priors: dict[str, Prior] = field(default_factory=dict)

    def load(self) -> "PriorStore":
        if os.path.exists(self.path):
            raw = json.load(open(self.path))
            self.priors = {k: Prior(**v) for k, v in raw.items()}
        return self

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        json.dump({k: asdict(p) for k, p in self.priors.items()}, open(self.path, "w"), indent=2)

    def put(self, prior: Prior) -> None:
        """Insert or version-bump a prior (append-only versioning: a new value bumps version)."""
        existing = self.priors.get(prior.key)
        if existing and not existing.revoked:
            prior.version = existing.version + 1
        self.priors[prior.key] = prior

    def revoke(self, key: str) -> None:
        if key in self.priors:
            self.priors[key].revoked = True

    def active(self) -> dict[str, Prior]:
        return {k: p for k, p in self.priors.items() if not p.revoked}


def distill_priors(ledger_entries: list[dict], *, run_id: str,
                   antichain_widths: list[int] | None = None,
                   budget_actuals: dict | None = None) -> list[Prior]:
    """Distill a run's ledger into priors. Pure read; advisory output."""
    priors: list[Prior] = []
    # failure-mode signatures: steps that hit FAILED
    failed = [e["node"] for e in ledger_entries
              if e.get("kind") == "lifecycle-transition" and e.get("lifecycle_state") == "FAILED"]
    if failed:
        priors.append(Prior(key="failure_signatures", kind="failure-signature",
                            value=sorted(set(failed)), source_run=run_id))
    # plan-shape prior: typical antichain widths
    if antichain_widths:
        priors.append(Prior(key="antichain_widths", kind="plan-shape",
                            value=antichain_widths, source_run=run_id))
    # budget calibration: predicted vs actual thinking tiers
    if budget_actuals:
        priors.append(Prior(key="budget_calibration", kind="budget-calibration",
                            value=budget_actuals, source_run=run_id))
    return priors


def prior_to_scheduling_hint(store: PriorStore) -> dict:
    """Translate active priors into an advisory scheduling/allocation hint (consumed by
    S-P2-context.apply_memory_priors). Returns {} when memory is empty (fail-safe)."""
    active = store.active()
    hint: dict = {}
    if "budget_calibration" in active:
        cal = active["budget_calibration"].value
        if isinstance(cal, dict) and cal.get("suggested_tier"):
            hint["suggested_tier"] = cal["suggested_tier"]
    return hint
