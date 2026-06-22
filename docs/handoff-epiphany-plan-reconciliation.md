# Co-tuning HANDOFF → epiphany-plan: schema ↔ emitter reconciliation (S-P7-handoff, DF-7, item h)

**Status:** ✅ RESOLVED 2026-06-01 (consumer-side tolerant reconciliation; see "Resolution" below).
Previously OPEN. The epiphany-executor build never blocked on this (INV-18 tolerant adapter path
was in place). Closed by accepting BOTH shapes on the consumer side + fixing the gate-semantics bug
found during the epiphany-report handoff.

## Resolution (2026-06-01)

Direction chosen: **consumer-side tolerant reconciliation** (neither emitter nor schema forced to
change; both the observed-emit triad AND the published-schema variant are accepted). Three layers:

1. **Executor MD path** (`epiphany_executor/md_normalizer.py`): a clean PASS plan that marks its
   coverage/structural gates as blocking-TYPE (`- **blocking:** true`) was being normalized to
   `gate_status.gate="BLOCKING"` and FALSE-HALTED at INV-17. Fixed: the gate level is keyed on the
   VERDICT (PASS→OPEN), never on the blocking-nature flag. Comma-separated requirement traces are
   now split into individual ids for the coverage matrix.
2. **Executor start gate** (`epiphany_executor/gate_defect.py`): `gate=="BLOCKING"` only halts when
   the verdict is not PASS (a passed blocking-type gate proceeds; real `blocking_defects` still halt
   independently).
3. **Harness JSON importer** (`goatcs-harness/epiphany_plan_importer.py`): `is_epiphany_plan` now
   recognizes the published-schema variant (`execution_order` + `steps` + `coverage_verdict`) in
   addition to the triad; `_coerce_schema_variant` maps it onto the triad (`build_order` from
   `execution_order`; `gate_status` from coverage/structural verdicts with PASS→OPEN semantics;
   `structural_faults`/`blocking_defects` on a FAIL). Already-triad docs pass through unchanged.

**Verified:** executor suite green (+6 integration tests on the real 48-step epiphany-report plan);
harness importer suite green (+5 schema-variant tests); end-to-end `plan.md → md_normalizer →
harness importer → GraphSpec` (48 nodes, gate OPEN, PROCEED). The table below is retained for
history; the adapter is now a no-op for the reconciled fields in both directions.

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
