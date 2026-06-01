"""Speculative dry-run look-ahead (S-P2-speculate, AX-05/08).

Before committing a wave, preview the upcoming antichain in throwaway worktrees: each step is
dry-run with irreversible effects STUBBED and NO ledger commit. Predictions (write-sets,
conflicts, effort) refine the scheduler's disjointness test (AX-01) and the context budget.
Side-effect-free + advisory: the real wave re-verifies.

This module is the deterministic harness around speculation. The actual worktree/sub-agent
dry-run is injected as a `dry_run_fn(step_id, contract) -> {predicted_outputs, effort, ...}` so
the logic is testable without spawning anything. A `dry_run_fn` that raises is treated as "no
prediction" (advisory degrades gracefully, never blocks).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .scheduler import FanoutBudget, _canonical_outputs


@dataclass
class Prediction:
    step_id: str
    predicted_outputs: set[str] = field(default_factory=set)
    effort: float | None = None
    stubbed_irreversible: bool = False
    error: str | None = None
    committed_ledger: bool = False   # MUST always be False (IC-P2sp invariant)


@dataclass
class SpeculationResult:
    predictions: dict[str, Prediction] = field(default_factory=dict)
    predicted_conflicts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def wrote_ledger(self) -> bool:
        return any(p.committed_ledger for p in self.predictions.values())


def speculate_antichain(antichain: list[str], contracts: dict[str, dict],
                        dry_run_fn: Callable[[str, dict], dict],
                        budget: FanoutBudget | None = None) -> SpeculationResult:
    """Dry-run the antichain (advisory). Skips speculation below the budget's width threshold
    (not worth the worktrees). Never commits a ledger entry; an irreversible step's effects are
    expected to be stubbed by `dry_run_fn` and the result is flagged `stubbed_irreversible`.
    Returns predicted write-sets + predicted pairwise conflicts that refine the cohort.
    """
    budget = budget or FanoutBudget()
    res = SpeculationResult()
    if len(antichain) < budget.speculate_threshold:
        return res  # nothing worth speculating

    for sid in antichain:
        c = contracts[sid]
        try:
            out = dry_run_fn(sid, c) or {}
            if out.get("committed_ledger"):
                # IC-P2sp: speculation MUST NOT commit — refuse to trust a fn that did.
                raise RuntimeError("dry_run_fn committed a ledger entry during speculation")
            predicted = set(out.get("predicted_outputs") or [])
            # fall back to the static declared footprint if the dry-run predicted nothing
            if not predicted:
                predicted = _canonical_outputs(c)
            res.predictions[sid] = Prediction(
                step_id=sid,
                predicted_outputs=predicted,
                effort=out.get("effort"),
                stubbed_irreversible=bool(out.get("stubbed_irreversible")),
            )
        except Exception as ex:  # advisory: a failed prediction is just absent
            res.predictions[sid] = Prediction(step_id=sid, error=f"{type(ex).__name__}: {ex}")

    # predicted pairwise output conflicts (refines AX-01 disjointness with measured write-sets)
    ids = [p.step_id for p in res.predictions.values() if not p.error]
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            oa, ob = res.predictions[a].predicted_outputs, res.predictions[b].predicted_outputs
            if oa and ob and not oa.isdisjoint(ob):
                res.predicted_conflicts.append((a, b))
    return res


def refine_cohort(parallel: list[str], speculation: SpeculationResult) -> tuple[list[str], list[str]]:
    """Apply speculation's predicted conflicts to a planned cohort: any step in a predicted
    conflict is demoted to the serial residue (fail-closed — a *predicted* conflict is enough to
    pull it out, the real wave would discover it anyway). Returns (refined_parallel, demoted)."""
    conflicted: set[str] = set()
    for a, b in speculation.predicted_conflicts:
        conflicted.add(b)  # keep the earlier (build_order-stable) member, demote the later
    refined = [s for s in parallel if s not in conflicted]
    demoted = [s for s in parallel if s in conflicted]
    return refined, demoted
