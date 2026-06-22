"""Step lifecycle state machine + step-granular recovery cursor (S-P3-lifecycle, INV-3/5).

REUSES the harness substrate by name (INV-3 — no private store):
  - `goatcs_harness.ledger.append/read` — the append-only audit ledger; each lifecycle
    transition is a ledger entry, so current state is the FOLD over entries (INV-6) and
    kill+resume reconstructs lifecycle from the ledger alone.
  - `goatcs_harness.persist.make_persister` (Burr SQLitePersister) — the checkpoint; the
    recovery cursor {step_id, lifecycle_state, effect_ledger_cursor} rides Burr state.

No ACCEPTED step ever re-runs on resume (INV-5): the resume scheduler skips any step whose
folded lifecycle is ACCEPTED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .scheduler import static_effect_class


class LifecycleState(str, Enum):
    UNSTARTED = "UNSTARTED"
    IN_FLIGHT = "IN_FLIGHT"
    VERIFIED = "VERIFIED"
    ACCEPTED = "ACCEPTED"        # terminal success
    BLOCKED = "BLOCKED"          # precondition unmet (handoff to a differently-capable effector)
    FAILED = "FAILED"            # DoD failed after execution (halt + recover)
    AMENDED = "AMENDED"          # superseded by a ledgered plan-amendment delta
    AWAITING = "AWAITING"        # background Task in flight (joined at barrier)


# run-level aggregate (spec §5.6) — not a per-step state.
RUN_PARTIAL = "PARTIAL"

LEGAL_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.UNSTARTED: {LifecycleState.IN_FLIGHT, LifecycleState.BLOCKED,
                               LifecycleState.AWAITING},
    LifecycleState.AWAITING: {LifecycleState.IN_FLIGHT, LifecycleState.BLOCKED,
                              LifecycleState.FAILED},
    LifecycleState.IN_FLIGHT: {LifecycleState.VERIFIED, LifecycleState.FAILED,
                               LifecycleState.BLOCKED},
    LifecycleState.VERIFIED: {LifecycleState.ACCEPTED, LifecycleState.FAILED},
    # ACCEPTED -> needs-re-verify is an explicit re-open transition (INV-7): ACCEPTED->IN_FLIGHT
    # only via an AMENDED supersession path, never silently.
    LifecycleState.ACCEPTED: {LifecycleState.AMENDED},
    LifecycleState.AMENDED: {LifecycleState.IN_FLIGHT},
    LifecycleState.BLOCKED: {LifecycleState.IN_FLIGHT, LifecycleState.UNSTARTED},
    LifecycleState.FAILED: {LifecycleState.IN_FLIGHT, LifecycleState.UNSTARTED},  # via recovery
}

TERMINAL_SUCCESS = {LifecycleState.ACCEPTED}
HALT_STATES = {LifecycleState.FAILED, LifecycleState.BLOCKED}


class IllegalTransition(Exception):
    pass


def transition(current: LifecycleState, target: LifecycleState) -> LifecycleState:
    """Validate a lifecycle transition; raise IllegalTransition on an illegal edge (fail-closed).
    An ACCEPTED step cannot be silently moved back to IN_FLIGHT (INV-7 re-open discipline)."""
    if target not in LEGAL_TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"{current.value} -> {target.value} is not a legal transition")
    return target


def count_irreversible_effects(contract: dict) -> int:
    """Flag multi-irreversible steps at import (F-13). The static layer counts declared outputs
    that name an irreversible marker; a step with >1 is a v1 reliability risk (recovery unit is
    the whole step)."""
    if static_effect_class(contract) != "externally-irreversible":
        return 0
    from .scheduler import _IRREVERSIBLE_MARKERS
    fp = (contract.get("effect") or {}).get("footprint") or {}
    n = 0
    for out in fp.get("declared_outputs") or []:
        low = str(out).lower()
        if any(m in low for m in _IRREVERSIBLE_MARKERS):
            n += 1
    return n


def is_multi_irreversible(contract: dict) -> bool:
    return count_irreversible_effects(contract) > 1


@dataclass
class RecoveryCursor:
    step_id: str
    lifecycle_state: LifecycleState
    effect_ledger_cursor: int = 0          # last committed effect index for this step

    def as_entry(self) -> dict:
        return {"node": self.step_id, "lifecycle_state": self.lifecycle_state.value,
                "effect_ledger_cursor": self.effect_ledger_cursor,
                "kind": "lifecycle-transition"}


class LifecycleStore:
    """Append-only lifecycle store backed by the harness ledger (INV-3/6). Current state = fold."""

    def __init__(self, ledger_path: str):
        self._ledger_path = ledger_path

    def record(self, cursor: RecoveryCursor) -> None:
        from goatcs_harness import ledger as _ledger      # reuse the harness ledger (named symbol)
        _ledger.append(self._ledger_path, cursor.as_entry())

    def fold(self) -> dict[str, RecoveryCursor]:
        """Reconstruct each step's CURRENT lifecycle by folding the ledger (kill+resume safe)."""
        from goatcs_harness import ledger as _ledger
        cursors: dict[str, RecoveryCursor] = {}
        for entry in _ledger.read(self._ledger_path):
            if entry.get("kind") != "lifecycle-transition":
                continue
            sid = entry.get("node")
            if sid is None:
                continue
            cursors[sid] = RecoveryCursor(
                step_id=sid,
                lifecycle_state=LifecycleState(entry["lifecycle_state"]),
                effect_ledger_cursor=int(entry.get("effect_ledger_cursor", 0)),
            )
        return cursors

    def accepted_steps(self) -> set[str]:
        """Steps that must NOT re-run on resume (INV-5)."""
        return {sid for sid, c in self.fold().items()
                if c.lifecycle_state in TERMINAL_SUCCESS}


def make_burr_checkpoint(db_path: str):
    """Obtain the harness Burr persister (INV-3 — reuse, not a new store). The recovery cursor
    rides Burr state; the ledger fold is the authority for lifecycle reconstruction."""
    from goatcs_harness import persist as _persist
    return _persist.make_persister(db_path)


@dataclass
class BarrierCommit:
    """Ledger commits happen in deterministic build_order at the wave barrier (CV-01)."""
    build_order: list[str] = field(default_factory=list)

    def order_cursors(self, cursors: list[RecoveryCursor]) -> list[RecoveryCursor]:
        rank = {sid: i for i, sid in enumerate(self.build_order)}
        return sorted(cursors, key=lambda c: rank.get(c.step_id, len(rank)))
