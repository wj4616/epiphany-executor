"""Wave-parallel topological scheduler (S-P2-scheduler, AX-01/08, INV-8/16, CV-02/03).

Computes the executor's execution plan: a sequence of **waves**. Each wave is a *cohort* of
steps that may run concurrently (one effector sub-agent per step, each in its own git worktree,
AX-08) plus a must-serialize residue. The actual sub-agent/worktree dispatch is runtime
behavior (S-P3); this module computes the safe wave structure deterministically so it is
testable without spawning anything.

Safety (binding):
- A node joins a parallel cohort ONLY if it is **edge-independent** (no DAG path between it and
  a cohort sibling) AND **output-disjoint** (canonicalized write-sets) AND **statically provable
  non-irreversible** AND shares no external resource (INV-8/16). Else it drops to the serial
  residue. Default is serial unless independence is *provable* (fail-closed).
- The conflict graph is rooted in the **STATIC per-effect-class footprint** carried on the
  contract (CV-02) — NOT the runtime footprint S-P5 measures post-hoc. `outputs[]` is a LOWER
  bound: a step with undeclared outputs conflicts-with-all (INV-16).
- The cycle pre-flight EXCLUDES refinement back-edges (INV-8).
- A **fan-out budget** (CV-03) caps concurrent effectors / jury width / speculation; when a
  cohort would exceed it, the overflow degrades to serial.
- `--serial` ⇒ every wave has width 1 (the boring-baseline-compatible path / bootstrap fallback).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

# external-effect markers: a declared output naming any of these is treated as
# externally-irreversible at the STATIC layer (conservative; S-P5 refines pre-exec).
_IRREVERSIBLE_MARKERS = (
    "http://", "https://", "ssh://", "git@", "s3://", "gs://",
    "publish", "deploy", "release", "push", "send", "email", "post ",
    "tweet", "upload", "notify", "webhook", "api/", "://",
)


class SchedulerError(Exception):
    """Raised on a cycle in the forward DAG (excluding back-edges) — fail closed."""


@dataclass
class FanoutBudget:
    """CV-03 — caps on the machine-advantage levers; overflow degrades to serial."""
    max_concurrent_effectors: int = 8
    max_jury_width: int = 3
    speculate_threshold: int = 2   # min cohort width to bother speculating (AX-05)

    def __post_init__(self) -> None:
        if self.max_concurrent_effectors < 1:
            raise ValueError("max_concurrent_effectors must be >= 1")


@dataclass
class Wave:
    """One scheduled wave: a parallel cohort (concurrent) + a serial residue (run one-by-one
    after the cohort, in build_order)."""
    index: int
    parallel: list[str] = field(default_factory=list)
    serial: list[str] = field(default_factory=list)

    @property
    def width(self) -> int:
        return len(self.parallel)

    @property
    def all_steps(self) -> list[str]:
        return list(self.parallel) + list(self.serial)


# --------------------------------------------------------------------------- contracts


def extract_contracts(spec) -> dict[str, dict]:
    """Pull the stamped per-node COMPILE contracts off a loaded GraphSpec (one per step)."""
    out: dict[str, dict] = {}
    for nid, node in spec.nodes.items():
        sc = getattr(node, "step_contract", None)
        if isinstance(sc, dict):
            out[nid] = sc
    return out


def static_effect_class(contract: dict) -> str:
    """The STATIC per-effect-class footprint signal for scheduling (CV-02, INV-16).

    Conservative: a step whose declared outputs name an external/irreversible marker is
    `externally-irreversible`; a step with NO declared outputs is `unknown` (conflicts-with-all);
    otherwise `local-mutating`. The concrete per-command class is set pre-execution by S-P5
    (INV-15) — this is only the scheduling-time lower bound.
    """
    fp = (contract.get("effect") or {}).get("footprint") or {}
    declared = fp.get("declared_outputs") or []
    if fp.get("conflicts_with_all") or not declared:
        return "unknown"
    for out in declared:
        low = str(out).lower()
        if any(m in low for m in _IRREVERSIBLE_MARKERS):
            return "externally-irreversible"
    return "local-mutating"


def _canonical_outputs(contract: dict) -> set[str]:
    """Canonicalize declared output paths (realpath/symlink/case) before conflict comparison
    (INV-16). Non-path outputs are kept verbatim (still compared for equality)."""
    fp = (contract.get("effect") or {}).get("footprint") or {}
    out: set[str] = set()
    for o in fp.get("declared_outputs") or []:
        s = str(o)
        try:
            c = os.path.normcase(os.path.realpath(os.path.expanduser(s))) if ("/" in s or os.sep in s) else s
        except OSError:
            c = s
        out.add(c)
    return out


# --------------------------------------------------------------------------- DAG


def build_dag(contracts: dict[str, dict], build_order: list | None = None) -> dict[str, set[str]]:
    """Build the forward dependency DAG {step_id -> set(prerequisite step_ids)} from each step's
    normalized `dependencies` (implementation-prerequisite + ordering edges). `build_order`, when
    it is a clean step-id sequence, adds coarse ordering; prose build_order is ignored here (the
    real runs carry prose — per-step deps are the ordering authority, INV-18/BD-4)."""
    ids = set(contracts)
    dag: dict[str, set[str]] = {sid: set() for sid in ids}
    for sid, c in contracts.items():
        for dep in c.get("dependencies") or []:
            on = dep.get("on")
            if on in ids and on != sid:
                dag[sid].add(on)
    # build_order: only consume it when it is an explicit list of known step-ids.
    if build_order and all(isinstance(x, str) for x in build_order):
        seq = [x for x in build_order if x in ids]
        if len(seq) >= 2 and len(set(seq)) == len(seq):
            for prev, cur in zip(seq, seq[1:]):
                dag[cur].add(prev)
    return dag


def detect_cycle(dag: dict[str, set[str]]) -> list[str]:
    """Return a cycle path if the forward DAG has one (back-edges are not in `dag`), else []."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in dag}
    stack: list[str] = []

    def dfs(n: str) -> list[str]:
        color[n] = GRAY
        stack.append(n)
        for m in dag.get(n, ()):
            if color.get(m, WHITE) == GRAY:
                return stack[stack.index(m):] + [m]
            if color.get(m, WHITE) == WHITE:
                r = dfs(m)
                if r:
                    return r
        color[n] = BLACK
        stack.pop()
        return []

    for n in dag:
        if color[n] == WHITE:
            r = dfs(n)
            if r:
                return r
    return []


def topo_layers(dag: dict[str, set[str]]) -> list[list[str]]:
    """Kahn layering: each layer is an *antichain* (no path between members) of steps whose
    prerequisites are all already scheduled. Raises SchedulerError on a cycle (fail-closed)."""
    cyc = detect_cycle(dag)
    if cyc:
        raise SchedulerError(f"cycle in forward DAG (excluding back-edges): {' -> '.join(cyc)}")
    remaining = {n: set(p) for n, p in dag.items()}
    done: set[str] = set()
    layers: list[list[str]] = []
    while remaining:
        ready = sorted(n for n, p in remaining.items() if p <= done)
        if not ready:  # defensive — should not happen post cycle-check
            raise SchedulerError("scheduling stalled (unsatisfiable prerequisites)")
        layers.append(ready)
        done |= set(ready)
        for n in ready:
            remaining.pop(n)
    return layers


# --------------------------------------------------------------------------- cohorts


def _provably_disjoint(a: dict, b: dict) -> bool:
    """Two steps are output-disjoint iff their canonicalized declared write-sets don't intersect
    AND both actually declared outputs (undeclared = conflicts-with-all, INV-16)."""
    oa, ob = _canonical_outputs(a), _canonical_outputs(b)
    if not oa or not ob:
        return False
    return oa.isdisjoint(ob)


def partition_cohort(antichain: list[str], contracts: dict[str, dict],
                     budget: FanoutBudget) -> tuple[list[str], list[str]]:
    """Split an antichain into (parallel-eligible cohort, must-serialize residue).

    A step is parallel-eligible iff it is statically non-irreversible (local-mutating), has
    declared outputs, and is pairwise output-disjoint from every other cohort member. The first
    conflicting/irreversible/undeclared step in build_order order stays; conflicters drop to the
    residue (fail-closed). The cohort is then capped at `max_concurrent_effectors` (CV-03);
    overflow degrades to serial.
    """
    parallel: list[str] = []
    serial: list[str] = []
    for sid in antichain:  # antichain is already build_order-stable (sorted in topo_layers)
        c = contracts[sid]
        eligible = static_effect_class(c) == "local-mutating"
        if eligible:
            # must be disjoint from every step already admitted to the cohort
            if all(_provably_disjoint(c, contracts[p]) for p in parallel):
                if len(parallel) < budget.max_concurrent_effectors:
                    parallel.append(sid)
                else:
                    serial.append(sid)        # CV-03 budget overflow -> serial
                continue
        serial.append(sid)
    # a width-1 "cohort" is just a serial step — normalize so callers see honest widths.
    if len(parallel) == 1:
        serial.insert(0, parallel.pop())
    return parallel, serial


def schedule_waves(contracts: dict[str, dict], build_order: list | None = None,
                   budget: FanoutBudget | None = None, serial: bool = False) -> list[Wave]:
    """Produce the ordered list of waves. `serial=True` forces width-1 waves (the `--serial`
    fallback / INV-14 bootstrap base case)."""
    budget = budget or FanoutBudget()
    dag = build_dag(contracts, build_order)
    layers = topo_layers(dag)
    waves: list[Wave] = []
    for i, layer in enumerate(layers):
        if serial:
            waves.append(Wave(index=i, parallel=[], serial=list(layer)))
        else:
            par, ser = partition_cohort(layer, contracts, budget)
            waves.append(Wave(index=i, parallel=par, serial=ser))
    return waves


def schedule_summary(waves: Iterable[Wave]) -> dict:
    """Telemetry-friendly summary (feeds S-P5-telemetry CV-03 fan-out view)."""
    waves = list(waves)
    return {
        "n_waves": len(waves),
        "max_cohort_width": max((w.width for w in waves), default=0),
        "n_parallel_steps": sum(w.width for w in waves),
        "n_serial_steps": sum(len(w.serial) for w in waves),
    }
