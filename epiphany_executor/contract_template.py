"""Per-node COMPILE contract template (S-P0-contracts).

In the COMPILE model, the importer (S-P1) turns each epiphany-plan *step* into one harness
*node*. `stamp_node_contract` produces the per-node contract fields the executor's lifecycle,
DoD verifier, scheduler, effect-classifier, and coverage layers all read. Every compiled node
carries the four binding field-groups (IC-P0c):

  - **lifecycle**  — the step lifecycle state (spec §5.6); starts UNSTARTED.
  - **DoD**        — Definition-of-Done = acceptance_criteria ∪ integration_checks ∪ outputs
                     (spec §2; evaluated at the harness fidelity gate, S-P3-dod).
  - **effect**     — effect_class (pure|local-mutating|externally-irreversible) + the STATIC
                     per-effect-class footprint published pre-schedule (CV-02). The concrete
                     per-command class is set pre-execution by S-P5 (INV-15); at stamp time it
                     is `unclassified` with the conservative scheduling footprint = declared
                     outputs (or conflicts-with-all when outputs are undeclared, INV-16).
  - **traces**     — requirement-coverage closure keys (traces_to / traces_requirements).

The function is tolerant of BOTH the real emitted shape and the plan.schema.json shape
(INV-18) so the importer can call it on adapter output OR raw steps:
  - `integration_checks` may be a single object {id,assert,status} OR a list.
  - requirement tracing may be `traces_to` OR `traces_requirements`.
  - `dependencies` may be bare step_id strings OR typed {on,kind,edge_class} objects.
No field is silently dropped (INV-2): unknown keys are preserved under `extra`.
"""
from __future__ import annotations

from typing import Any

LIFECYCLE_STATES = (
    "UNSTARTED", "IN_FLIGHT", "VERIFIED", "ACCEPTED",
    "BLOCKED", "FAILED", "AMENDED", "AWAITING",
)
EFFECT_CLASSES = ("pure", "local-mutating", "externally-irreversible")

# the canonical per-node contract field-groups; the importer asserts a stamped node has these.
CONTRACT_FIELD_GROUPS = ("lifecycle", "dod", "effect", "traces")

_KNOWN_STEP_KEYS = {
    "step_id", "goal", "actions", "inputs", "outputs", "dependencies",
    "integration_checks", "acceptance_criteria", "traces_to", "traces_requirements",
    "phase", "refinement_back_edges",
}


def _as_list(x: Any) -> list:
    """Tolerate object|list|None for fields that are a list in schema but an object in the
    real emit (e.g. integration_checks)."""
    if x is None:
        return []
    if isinstance(x, list):
        return list(x)
    return [x]


def _traces(step: dict) -> list:
    """`traces_to` (real emit) ↔ `traces_requirements` (schema) — neither dropped (INV-18)."""
    t = step.get("traces_to")
    if t is None:
        t = step.get("traces_requirements")
    return _as_list(t)


def _normalize_deps(step: dict) -> list[dict]:
    """Bare-string deps (real emit) -> ordering-prerequisite records; typed deps pass through
    with their edge_class (INV-18)."""
    out: list[dict] = []
    for dep in _as_list(step.get("dependencies")):
        if isinstance(dep, str):
            out.append({"on": dep, "kind": "ordering", "edge_class": "ordering",
                        "from_typed": False})
        elif isinstance(dep, dict):
            out.append({"on": dep.get("on"),
                        "kind": dep.get("kind", "ordering"),
                        "edge_class": dep.get("edge_class", "ordering"),
                        "from_typed": True})
    return out


def _static_footprint(outputs: list) -> dict:
    """The STATIC per-effect-class footprint for the scheduler (CV-02, INV-16). Declared
    `outputs[]` is a LOWER BOUND; a step with no declared outputs conflicts-with-all (forced
    serial). Canonicalization of paths happens in the scheduler (S-P2)."""
    declared = [o if isinstance(o, str) else (o.get("path") or o.get("name"))
                for o in outputs]
    declared = [d for d in declared if d]
    return {"declared_outputs": declared,
            "conflicts_with_all": len(declared) == 0}


def stamp_node_contract(step: dict) -> dict:
    """Stamp one plan step into the per-node COMPILE contract (IC-P0c).

    Returns a dict carrying all four CONTRACT_FIELD_GROUPS. The lifecycle starts UNSTARTED;
    effect_class starts `unclassified` (set pre-execution by S-P5, INV-15) while the static
    scheduling footprint is available immediately (CV-02).
    """
    if not isinstance(step, dict):
        raise TypeError(f"step must be a dict, got {type(step).__name__}")
    step_id = step.get("step_id")
    if not step_id:
        raise ValueError("step is missing required 'step_id'")

    acceptance = _as_list(step.get("acceptance_criteria"))
    integration = _as_list(step.get("integration_checks"))
    outputs = _as_list(step.get("outputs"))

    contract = {
        "step_id": step_id,
        "goal": step.get("goal", ""),
        "actions": _as_list(step.get("actions")),
        "inputs": _as_list(step.get("inputs")),
        "dependencies": _normalize_deps(step),
        # --- the four binding field-groups (IC-P0c) ---
        "lifecycle": {
            "state": "UNSTARTED",
            "history": [],            # append-only lifecycle transitions (filled at runtime)
        },
        "dod": {
            # DoD = acceptance_criteria ∪ integration_checks ∪ outputs (spec §2)
            "acceptance_criteria": acceptance,
            "integration_checks": integration,
            "outputs": outputs,
            # INV-10 fail-closed: a step with no acceptance criteria is unverifiable -> BLOCKED.
            "verifiable": bool(acceptance) or bool(integration),
        },
        "effect": {
            "effect_class": "unclassified",   # set pre-execution by S-P5 (INV-15)
            "footprint": _static_footprint(outputs),
        },
        "traces": _traces(step),
        # INV-2: preserve any unknown keys rather than dropping them.
        "extra": {k: v for k, v in step.items() if k not in _KNOWN_STEP_KEYS},
    }
    return contract


def assert_node_contract(contract: dict) -> None:
    """IC-P0c assertion: a compiled node carries lifecycle + DoD + effect + traces fields.
    Raises AssertionError on a malformed contract (fail-closed)."""
    for group in CONTRACT_FIELD_GROUPS:
        assert group in contract, f"compiled node contract missing field-group {group!r}"
    assert contract["lifecycle"]["state"] in LIFECYCLE_STATES, "illegal lifecycle state"
    dod = contract["dod"]
    for k in ("acceptance_criteria", "integration_checks", "outputs"):
        assert k in dod, f"DoD missing {k!r}"
    assert "effect_class" in contract["effect"], "effect missing effect_class"
    assert "footprint" in contract["effect"], "effect missing static footprint"
