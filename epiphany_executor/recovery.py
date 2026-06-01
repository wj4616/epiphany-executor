"""INV-1 reliability/recovery envelope + R-023 forced-fail + wave rollback (S-P3-recovery,
PC-01, CV-01).

On a FAILED DoD the step is NEVER marked complete: the executor halts, checkpoints, and offers a
recovery menu (retry / rollback / fork / skip-with-waiver / halt-for-human). The human decision
is routed through the S-P5-telemetry resolution surface. A mid-wave failure discards the staged
cohort worktrees so no sibling persists — the PRE-WAVE checkpoint is the recovery point (CV-01).
Rolling back an externally-irreversible effect is FORBIDDEN (INV-7) and surfaced as a
human-review item.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .lifecycle import LifecycleState
from .scheduler import static_effect_class


class RecoveryOption(str, Enum):
    RETRY = "retry"
    ROLLBACK = "rollback"               # worktree discard / git revert (reversible only)
    FORK = "fork"                       # branch a new session from a prior seq
    SKIP_WITH_WAIVER = "skip-with-waiver"   # only if downstream-safe
    HALT_FOR_HUMAN = "halt-for-human"


def recovery_menu(contract: dict, *, downstream_safe: bool) -> list[RecoveryOption]:
    """Build the recovery menu for a failed step. ROLLBACK is offered only when the step is not
    externally-irreversible (INV-7); SKIP only when downstream-safe; RETRY/FORK/HALT always."""
    menu = [RecoveryOption.RETRY, RecoveryOption.FORK, RecoveryOption.HALT_FOR_HUMAN]
    if static_effect_class(contract) != "externally-irreversible":
        menu.insert(1, RecoveryOption.ROLLBACK)
    if downstream_safe:
        menu.append(RecoveryOption.SKIP_WITH_WAIVER)
    return menu


@dataclass
class HaltState:
    """A checkpointed, resumable halt. The step is NOT ACCEPTED (R-023)."""
    step_id: str
    lifecycle_state: LifecycleState
    checkpoint_seq: int
    menu: list[RecoveryOption]
    reason: str
    not_accepted: bool = True
    forbidden_rollback: bool = False    # true when an irreversible effect bars rollback (INV-7)

    def __post_init__(self) -> None:
        # invariant: a halted step is never ACCEPTED.
        assert self.lifecycle_state is not LifecycleState.ACCEPTED, "halted step must not be ACCEPTED"


def on_verify_fail(contract: dict, *, checkpoint_seq: int, downstream_safe: bool = False,
                   reason: str = "DoD failed") -> HaltState:
    """R-023: a forced acceptance-fail halts + checkpoints + offers recovery with the step NOT
    complete. Never silent corruption."""
    menu = recovery_menu(contract, downstream_safe=downstream_safe)
    irreversible = static_effect_class(contract) == "externally-irreversible"
    return HaltState(
        step_id=contract.get("step_id", "?"),
        lifecycle_state=LifecycleState.FAILED,
        checkpoint_seq=checkpoint_seq,
        menu=menu,
        reason=reason,
        forbidden_rollback=irreversible,
    )


@dataclass
class WaveRollbackResult:
    discarded_worktrees: list[str] = field(default_factory=list)
    recovery_checkpoint_seq: int = 0
    committed_state_advanced: bool = False   # MUST stay False (pre-wave checkpoint stands)


def wave_rollback(staged_worktrees: list[str], pre_wave_checkpoint_seq: int,
                  discard_fn: Callable[[str], None]) -> WaveRollbackResult:
    """CV-01: on a mid-wave failure, discard ALL staged cohort worktrees so no sibling persists;
    the committed state stays at the pre-wave checkpoint (recovery point). Atomic all-or-nothing:
    a partially-applied wave never persists."""
    discarded: list[str] = []
    for wt in staged_worktrees:
        discard_fn(wt)          # git worktree remove (runtime); injected for testability
        discarded.append(wt)
    return WaveRollbackResult(
        discarded_worktrees=discarded,
        recovery_checkpoint_seq=pre_wave_checkpoint_seq,
        committed_state_advanced=False,
    )
