"""The boring-baseline sequential applier (S-P6-baseline, PC-04, INV-14 bootstrap).

The benchmark comparator AND the INV-14 bootstrap base case (when the executor itself is broken,
this is the fallback applier). Specified capabilities (deliberately MINIMAL so the benchmark
delta is attributable to the executor's additive layer, not a handicap):

  HAS: reads the plan in build_order, applies each step's actions in order, checks each step's
       acceptance_criteria (a single objective check), stops on first failure.
  HAS NOT: look-ahead, back-update, forward-delta, wave parallelism, effect taxonomy / gating,
           checkpoint/resume, jury, drift detection, coverage closure.

It is frozen: this is the honest "human-by-hand sequential applier with an acceptance check"
the executor must strictly beat on the decisive axes (back-update + recovery).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

BASELINE_CAPABILITIES = {
    "reads_plan": True,
    "applies_actions_in_order": True,
    "checks_acceptance": True,
    "look_ahead": False,
    "back_update": False,
    "forward_delta": False,
    "wave_parallel": False,
    "effect_taxonomy": False,
    "checkpoint_resume": False,
    "jury": False,
    "drift_detection": False,
    "coverage_closure": False,
}


@dataclass
class BaselineResult:
    accepted: list[str] = field(default_factory=list)
    failed_at: str | None = None
    total: int = 0

    @property
    def end_to_end_success(self) -> bool:
        return self.failed_at is None and len(self.accepted) == self.total

    @property
    def verified_step_rate(self) -> float:
        return len(self.accepted) / self.total if self.total else 0.0


def run_baseline(plan: dict, *, apply_fn: Callable[[dict], dict],
                 check_fn: Callable[[dict, dict], bool]) -> BaselineResult:
    """Apply steps in build_order (or document order). `apply_fn(step)->artifacts`;
    `check_fn(step, artifacts)->bool` is the single acceptance check. Stops on first failure (no
    recovery, no checkpoint). NOTHING more."""
    steps = plan.get("steps", [])
    by_id = {s["step_id"]: s for s in steps if isinstance(s, dict) and s.get("step_id")}
    order = [s["step_id"] for s in steps if isinstance(s, dict) and s.get("step_id")]
    res = BaselineResult(total=len(order))
    for sid in order:
        step = by_id[sid]
        artifacts = apply_fn(step) or {}
        if check_fn(step, artifacts):
            res.accepted.append(sid)
        else:
            res.failed_at = sid
            break               # boring: halt on first failure, no recovery/rollback offer
    return res
