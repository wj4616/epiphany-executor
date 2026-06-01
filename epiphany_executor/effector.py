"""Wave effector fan-out + barrier (S-P3-effector-fanout, AX-01/06/08).

Dispatches one effector per cohort step, each in its OWN git worktree (AX-08, no cross-worktree
race), at its allocated thinking tier (AX-02). Long-running actions launch as background Tasks
(lifecycle AWAITING) and are joined at the barrier (AX-06). The BARRIER collects all results
(uncommitted) before verification (S-P3-dod) — staging, not committing (CV-01 atomic wave).

The actual sub-agent spawn + git-worktree ops are RUNTIME concerns, injected as `dispatch_fn`
and a `WorktreeManager`, so the orchestration is deterministically testable. Results are
STAGED (not ledger-committed) here; commit happens only if the whole wave passes verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .scheduler import Wave


class WorktreeManager(Protocol):
    def create(self, step_id: str) -> str: ...
    def merge(self, worktree: str) -> None: ...
    def discard(self, worktree: str) -> None: ...


class _InMemoryWorktrees:
    """Default test/dev worktree manager — distinct path per step, no real git ops."""
    def __init__(self) -> None:
        self.created: list[str] = []
        self.merged: list[str] = []
        self.discarded: list[str] = []

    def create(self, step_id: str) -> str:
        path = f"<worktree:{step_id}>"
        self.created.append(path)
        return path

    def merge(self, worktree: str) -> None:
        self.merged.append(worktree)

    def discard(self, worktree: str) -> None:
        self.discarded.append(worktree)


@dataclass
class StepResult:
    step_id: str
    worktree: str
    artifacts: dict = field(default_factory=dict)
    background: bool = False
    joined: bool = False
    error: str | None = None
    committed: bool = False     # MUST be False at the barrier (staged, not committed)


@dataclass
class WaveResult:
    index: int
    results: dict[str, StepResult] = field(default_factory=dict)

    @property
    def all_ok(self) -> bool:
        return all(r.error is None for r in self.results.values())

    @property
    def any_committed(self) -> bool:
        return any(r.committed for r in self.results.values())

    def worktrees(self) -> list[str]:
        return [r.worktree for r in self.results.values()]


def dispatch_wave(wave: Wave, contracts: dict[str, dict], *,
                  dispatch_fn: Callable[[str, dict, str], dict],
                  worktrees: WorktreeManager | None = None,
                  is_background: Callable[[str, dict], bool] | None = None,
                  join_fn: Callable[[str], dict] | None = None) -> WaveResult:
    """Run a wave: parallel cohort steps each in their own worktree, serial residue one-by-one
    after. Long actions (is_background) launch AWAITING and join at the barrier. Returns staged
    (uncommitted) results. No cross-worktree race: each step gets a distinct worktree path.
    """
    worktrees = worktrees or _InMemoryWorktrees()
    is_background = is_background or (lambda s, c: False)
    result = WaveResult(index=wave.index)
    seen_paths: set[str] = set()

    def _run(step_id: str) -> StepResult:
        c = contracts[step_id]
        wt = worktrees.create(step_id)
        assert wt not in seen_paths, f"cross-worktree race: duplicate worktree {wt}"
        seen_paths.add(wt)
        try:
            if is_background(step_id, c):
                # background Task: launched now, joined at the barrier (AWAITING)
                sr = StepResult(step_id=step_id, worktree=wt, background=True)
                joined = (join_fn or dispatch_fn)(step_id) if join_fn else dispatch_fn(step_id, c, wt)
                sr.artifacts = joined or {}
                sr.joined = True
                return sr
            artifacts = dispatch_fn(step_id, c, wt) or {}
            return StepResult(step_id=step_id, worktree=wt, artifacts=artifacts)
        except Exception as ex:
            return StepResult(step_id=step_id, worktree=wt, error=f"{type(ex).__name__}: {ex}")

    # parallel cohort (semantics: independent; runtime runs them concurrently)
    for sid in wave.parallel:
        result.results[sid] = _run(sid)
    # serial residue, in order
    for sid in wave.serial:
        result.results[sid] = _run(sid)
    # BARRIER: all collected, nothing committed yet (CV-01)
    return result
