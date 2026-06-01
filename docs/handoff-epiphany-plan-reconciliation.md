# Co-tuning HANDOFF → epiphany-plan: schema ↔ emitter reconciliation (S-P7-handoff, DF-7, item h)

**Status:** OPEN handoff. **The epiphany-executor build does NOT block on this** (INV-18 tolerant
adapter path is in place and validated — S-P6-validate ALL_OK). This is a standing INV-12
co-tuning item against the **epiphany-plan** skill, with a re-verify-on-shared-corpus gate.

## The divergence (grounded in 3 real runs, §4.6 / BD-4)

`epiphany-plan --json` output diverges from its own `plan.schema.json`:

| schema (target) | real emit | executor adapter (tolerant, INV-18) |
|---|---|---|
| `dependencies: [{on,kind,edge_class}]` | bare `step_id` strings | bare → ordering-prerequisite; degrade to `build_order` |
| `integration_checks: [...]` (array) | single object `{id,assert,status}` | normalize object→list |
| `traces_requirements` | `traces_to` | field adapter |
| per-step `refinement_back_edges`, `phase` | absent (plan-level only) | plan-level back-edges consumed |
| `build_order: [step_id...]` | prose layer-label strings | parse step_ids from prose |
| `schema_version` / `$schema` | absent | triad discriminator (`build_order`+`steps`+`gate_status`) |

## The ask (either direction closes it)

1. **Emitter → schema:** epiphany-plan emits typed `dependencies` (+`edge_class`),
   `traces_requirements`, per-step `refinement_back_edges`, a structured `build_order` (step-id
   arrays), and a `schema_version`/`$schema` discriminator; **OR**
2. **Schema → emitter:** update `plan.schema.json` to the richer real shape (bare deps,
   `integration_checks` object, `traces_to`, plan-level keys) so the contract matches reality.

## Re-verify gate (cross-skill)

When either lands, re-run the **shared reference-plan regression corpus** (the 3 JSON runs + 6 MD
plans) through the epiphany-executor importer + `S-P6-validate`. The gate passes iff all plans
still ingest + validate with the divergence removed (the adapter becomes a no-op for the
reconciled fields). Until then the executor stays on the tolerant-adapter path.

Tracked as INV-12 item **h** / **BD-4** in `docs/INV-12-cotuning-tracker.md`.
