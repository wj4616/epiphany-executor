# Per-node COMPILE contract template (S-P0-contracts)

The executor uses the **COMPILE model** (spec §5): the importer (S-P1) turns each
epiphany-plan *step* into one harness *node*. Each compiled node is stamped with a contract by
`epiphany_executor.contract_template.stamp_node_contract(step) -> dict`. Every compiled node
carries the four binding field-groups (IC-P0c), each owned by a downstream layer:

| field-group | shape | consumed by | spec |
|---|---|---|---|
| **lifecycle** | `{state, history[]}`; state ∈ UNSTARTED/IN_FLIGHT/VERIFIED/ACCEPTED/BLOCKED/FAILED/AMENDED/AWAITING | lifecycle SM (S-P3-lifecycle) | §5.6 |
| **dod** | `{acceptance_criteria[], integration_checks[], outputs[], verifiable}` | DoD verifier (S-P3-dod) at the harness fidelity gate | §2, INV-10 |
| **effect** | `{effect_class, footprint:{declared_outputs[], conflicts_with_all}}` | scheduler reads STATIC footprint pre-schedule (CV-02); S-P5 sets the concrete `effect_class` pre-execution (INV-15) | §2, INV-15/16 |
| **traces** | requirement keys (`traces_to`/`traces_requirements`) | coverage closure (S-P5-coverage) | INV-2, F-10 |

## Tolerance (INV-18)

`stamp_node_contract` accepts BOTH the real emitted shape and the plan.schema.json shape so
the importer can call it on adapter output or raw steps:

- `integration_checks` object `{id,assert,status}` ↔ list — normalized to a list.
- `traces_to` (real emit) ↔ `traces_requirements` (schema) — neither dropped.
- `dependencies` bare strings ↔ typed `{on,kind,edge_class}` — bare → ordering-prerequisite
  (`from_typed=False`); typed preserve `edge_class` (`from_typed=True`).
- Unknown keys preserved under `extra` (INV-2 — no silent drop).

## Fail-closed defaults

- No `acceptance_criteria` and no `integration_checks` → `dod.verifiable = False` → the step is
  BLOCKED, never auto-passed (INV-10).
- No declared `outputs[]` → `footprint.conflicts_with_all = True` → forced serial (INV-16:
  `outputs[]` is a lower bound, not ground truth).
- `effect_class` starts `unclassified`; the concrete class is set **pre-execution** by S-P5,
  conservative default `externally-irreversible` for unclassifiable commands (INV-15).
- Missing `step_id` → `ValueError` (the importer fails closed).

Verification: `tests/test_contract_template.py` (10 tests) stamps a real goatcs-v3 step and
asserts all four field-groups + each tolerance/fail-closed rule.
