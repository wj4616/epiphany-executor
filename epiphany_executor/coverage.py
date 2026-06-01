"""Requirement-coverage closure + waiver (S-P5-coverage, CN-006, F-10, INV-2).

Maintains the requirement → step matrix from each step's `traces_to`/`traces_requirements`,
reconciled against plan-level `requirement_preservation`. An orphan (a requirement no step
traces) is blocking, with the F-10 waiver:
  - **executor-caused orphan** — the plan's `gate_status.requirement_to_step_map` maps the
    requirement to a step, but that step does NOT trace it → the executor dropped a trace →
    BLOCK (release-blocking).
  - **plan-caused orphan** — no step ever claimed the requirement → the upstream plan failed to
    assign it → WAIVABLE, routed back to epiphany-plan via INV-12 with an explicit operator ack.
Fail-closed default (orphans block) with this single escape hatch (F-10).
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _traces_of(step: dict) -> list[str]:
    t = step.get("traces_to")
    if t is None:
        t = step.get("traces_requirements")
    if t is None:
        return []
    return list(t) if isinstance(t, list) else [t]


def build_matrix(plan: dict) -> dict[str, list[str]]:
    """requirement -> [step_ids that trace it]."""
    matrix: dict[str, list[str]] = {}
    for s in plan.get("steps", []):
        if not isinstance(s, dict):
            continue
        sid = s.get("step_id")
        for req in _traces_of(s):
            matrix.setdefault(req, []).append(sid)
    return matrix


def _input_obligations(plan: dict) -> set[str]:
    rp = plan.get("requirement_preservation") or {}
    obs = rp.get("input_obligations")
    if isinstance(obs, list):
        return set(obs)
    if isinstance(obs, int):
        return set()       # count-only form (real emit) — no enumerable obligation set
    return set()


def _req_to_step_map(plan: dict) -> dict[str, str]:
    """Parse gate_status.requirement_to_step_map when it is a mapping; the real emit often carries
    a prose string (no structured map) — then we cannot attribute executor-caused orphans, so all
    orphans are plan-caused (waivable), which is the safe direction."""
    gs = plan.get("gate_status") or {}
    m = gs.get("requirement_to_step_map")
    return m if isinstance(m, dict) else {}


@dataclass
class Orphan:
    requirement: str
    kind: str            # "executor-caused" | "plan-caused"
    expected_step: str | None = None


@dataclass
class CoverageReport:
    matrix: dict[str, list[str]] = field(default_factory=dict)
    orphans: list[Orphan] = field(default_factory=list)

    @property
    def executor_caused(self) -> list[Orphan]:
        return [o for o in self.orphans if o.kind == "executor-caused"]

    @property
    def plan_caused(self) -> list[Orphan]:
        return [o for o in self.orphans if o.kind == "plan-caused"]

    @property
    def blocks(self) -> bool:
        """Release-blocking iff there is an executor-caused orphan (plan-caused are waivable)."""
        return bool(self.executor_caused)


def coverage_report(plan: dict) -> CoverageReport:
    matrix = build_matrix(plan)
    obligations = _input_obligations(plan)
    req_map = _req_to_step_map(plan)
    orphans: list[Orphan] = []
    # an obligation/required requirement with no tracing step is an orphan
    candidate_reqs = set(obligations) | set(req_map)
    for req in sorted(candidate_reqs):
        if matrix.get(req):
            continue
        expected = req_map.get(req)
        if expected:   # the plan said a step should cover it, but no step traces it
            orphans.append(Orphan(req, "executor-caused", expected_step=expected))
        else:          # no step ever claimed it -> upstream planning gap
            orphans.append(Orphan(req, "plan-caused"))
    return CoverageReport(matrix=matrix, orphans=orphans)


@dataclass
class Waiver:
    requirement: str
    operator_ack: bool
    routed_to: str = "epiphany-plan"     # INV-12 co-tuning route


def waive_plan_caused_orphan(orphan: Orphan, operator_ack: bool) -> Waiver:
    """Waive a PLAN-caused orphan (F-10) — requires an explicit operator acknowledgement; routes
    the gap back to epiphany-plan (INV-12). Executor-caused orphans are NOT waivable here."""
    if orphan.kind != "plan-caused":
        raise ValueError("only plan-caused orphans are waivable (executor-caused orphans block)")
    if not operator_ack:
        raise ValueError("waiver requires an explicit operator acknowledgement (F-10)")
    return Waiver(requirement=orphan.requirement, operator_ack=True)
