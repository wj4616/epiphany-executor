"""Post-step review: append-only back-update + forward-delta + background sentinel
(S-P4-review, AX-04/10, INV-6/7/11, CV-04, F-07).

After a step commits, the executor:
  - computes its `state_delta`;
  - if a plan-level `refinement_back_edge` rule is satisfied, fires a **back-update** — an
    APPEND-ONLY correcting delta (never mutates ledger history, INV-6) that re-opens the prior
    step's DoD as `needs-re-verify`. Bounded/terminating (INV-7): a revision budget caps depth;
    re-opening an ACCEPTED step is an explicit AMENDED→IN_FLIGHT transition; undoing an
    externally-irreversible effect is FORBIDDEN → human-review item; convergence (a round with no
    new deltas) is tracked.
  - propagates a **forward-delta**: successors whose inputs changed must consume REFRESHED
    look-ahead BEFORE they run (INV-11).

A background **sentinel** (AX-10) re-asserts every PASSED step's integration_checks after each
barrier (whole-plan regression detection). On a regression it appends a forward-delta and raises
a 1-firing back-edge — gated behind a monotonic epoch latch (CV-04: each regression triggers at
most one reschedule) and quiesced while a wave is in flight (cannot live-lock). The sentinel
ONLY appends; it never blocks the active wave.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .lifecycle import LifecycleState, RecoveryCursor
from .scheduler import static_effect_class


def compute_state_delta(before: dict, after: dict) -> dict:
    """The per-step change record (the substrate for look-behind, post-step diff, and
    back-update). Keys added/changed/removed between two state snapshots."""
    delta: dict = {"changed": {}, "added": {}, "removed": []}
    for k, v in after.items():
        if k not in before:
            delta["added"][k] = v
        elif before[k] != v:
            delta["changed"][k] = {"from": before[k], "to": v}
    for k in before:
        if k not in after:
            delta["removed"].append(k)
    return delta


@dataclass
class BackUpdateBudget:
    """INV-7: bounded/terminating back-update. `max_depth` caps propagation per plan; `max_total`
    caps the lifetime correcting-delta count. Exhaustion → halt + human gate."""
    max_depth: int = 5
    max_total: int = 50
    _spent: int = 0

    def charge(self) -> None:
        self._spent += 1
        if self._spent > self.max_total:
            raise BackUpdateExhausted(f"back-update budget exhausted ({self.max_total})")

    @property
    def spent(self) -> int:
        return self._spent


class BackUpdateExhausted(Exception):
    """INV-7: revision budget exhausted → halt + checkpoint + human gate."""


class IrreversibleUndoForbidden(Exception):
    """INV-7: a back-update may not undo an externally-irreversible effect (human-review item)."""


@dataclass
class ConvergenceTracker:
    """Tracks back-update convergence (a round with no new deltas = converged) — a success
    metric (F-07)."""
    rounds: list[int] = field(default_factory=list)

    def record_round(self, n_new_deltas: int) -> None:
        self.rounds.append(n_new_deltas)

    @property
    def converged(self) -> bool:
        return bool(self.rounds) and self.rounds[-1] == 0


@dataclass
class BackUpdate:
    target_step: str
    correcting_delta: dict
    reopened: bool
    depth: int


def back_update(target_contract: dict, correcting_delta: dict, *, depth: int,
                budget: BackUpdateBudget, ledger_append: Callable[[dict], None]) -> BackUpdate:
    """Fire an append-only correcting delta against `target_contract` and re-open its DoD.

    - APPEND-ONLY (INV-6): emits a new ledger entry via `ledger_append`; never edits history.
    - bounded (INV-7): charges the budget; `depth > budget.max_depth` raises BackUpdateExhausted.
    - irreversible guard (INV-7): re-opening a step that owns a committed externally-irreversible
      effect is FORBIDDEN → IrreversibleUndoForbidden (surfaced as a human-review item).
    """
    if depth > budget.max_depth:
        raise BackUpdateExhausted(f"back-update depth {depth} exceeds cap {budget.max_depth}")
    if static_effect_class(target_contract) == "externally-irreversible":
        raise IrreversibleUndoForbidden(
            f"cannot back-update step {target_contract.get('step_id')}: would undo an "
            f"externally-irreversible effect (human-review item, INV-7)")
    budget.charge()
    sid = target_contract.get("step_id", "?")
    entry = {"node": sid, "kind": "back-update-correcting-delta",
             "correcting_delta": correcting_delta, "depth": depth,
             "reopen": "needs-re-verify"}
    ledger_append(entry)
    # re-open the prior DoD: ACCEPTED -> AMENDED -> IN_FLIGHT (explicit, never silent — INV-7)
    return BackUpdate(target_step=sid, correcting_delta=correcting_delta, reopened=True, depth=depth)


def reopen_cursor(cursor: RecoveryCursor) -> list[RecoveryCursor]:
    """The explicit re-open transition sequence for an ACCEPTED step (INV-7). Returns the
    AMENDED then IN_FLIGHT cursors to append (never a silent forward-delta)."""
    if cursor.lifecycle_state is not LifecycleState.ACCEPTED:
        return [RecoveryCursor(cursor.step_id, LifecycleState.IN_FLIGHT, cursor.effect_ledger_cursor)]
    return [RecoveryCursor(cursor.step_id, LifecycleState.AMENDED, cursor.effect_ledger_cursor),
            RecoveryCursor(cursor.step_id, LifecycleState.IN_FLIGHT, cursor.effect_ledger_cursor)]


def propagate_forward_delta(dag: dict[str, set[str]], changed_step: str) -> set[str]:
    """INV-11: successors that depend on `changed_step` must refresh their look-ahead BEFORE they
    run. Returns the set of successor step_ids whose context is now stale."""
    return {s for s, deps in dag.items() if changed_step in deps}


# --------------------------------------------------------------------------- sentinel


@dataclass
class SentinelSignal:
    regressed_step: str
    epoch: int
    forward_delta: dict


class Sentinel:
    """Background ledger sentinel (AX-10). Re-asserts PASSED steps' integration_checks after each
    barrier; a regression appends a forward-delta and raises a 1-firing back-edge to the scheduler.
    CV-04: a monotonic epoch latch means each regression triggers AT MOST ONE reschedule, and the
    sentinel quiesces while a wave is in flight (no re-fire → cannot live-lock the active wave).
    Append-only: it never mutates state and never blocks.
    """

    def __init__(self) -> None:
        self._epoch = 0
        self._latched: set[tuple[str, int]] = set()   # (step, epoch) already fired

    @property
    def epoch(self) -> int:
        return self._epoch

    def advance_epoch(self) -> None:
        self._epoch += 1

    def sweep(self, passed_steps: list[str], reassert_fn: Callable[[str], bool], *,
              wave_in_flight: bool, ledger_append: Callable[[dict], None]) -> list[SentinelSignal]:
        """Re-assert each PASSED step's ICs. Returns the 1-firing back-edge signals. While a wave
        is in flight the sentinel QUIESCES (returns []) — CV-04 anti-live-lock."""
        if wave_in_flight:
            return []                       # quiesce: never re-fire against an active wave
        signals: list[SentinelSignal] = []
        for sid in passed_steps:
            ok = bool(reassert_fn(sid))
            if ok:
                continue
            key = (sid, self._epoch)
            if key in self._latched:        # 1-firing latch: at most one reschedule per epoch
                continue
            self._latched.add(key)
            fd = {"node": sid, "kind": "sentinel-regression-forward-delta", "epoch": self._epoch}
            ledger_append(fd)               # append-only; never blocks
            signals.append(SentinelSignal(regressed_step=sid, epoch=self._epoch, forward_delta=fd))
        return signals
