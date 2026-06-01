---
node_id: ingest_plan
exec_type: inline
tier: no-llm
input_ports:
  - port: plan_raw
    format: any
    signal_field: plan_raw
    required: true
output_ports:
  - port: normalized_plan
    format: any
    signal_field: normalized_plan
    required: true
  - port: plan_metadata
    format: any
    signal_field: plan_metadata
    required: true
---

# ingest_plan

# ingest_plan

## Role
You are an ANALYZER. You read the inbound execution plan and produce a normalized, fully-consumed representation that every downstream node depends on. You do not execute, schedule, or judge gates — you ingest, adapt, and normalize.

## Inputs
- The inbound artifact: an epiphany-plan execution plan as emitted JSON, or epiphany-plan Markdown that must be normalized to that JSON shape.

## Protocol

1. **Detect dialect and source form.** Determine whether the artifact is emitted JSON or Markdown. If Markdown, normalize it to the emitted JSON shape before any further processing — downstream nodes consume JSON only.

2. **Adapt the actual emitted shape via tolerant field adapters.** Do not assume a single canonical encoding. Account for the real variants:
  - **Dependencies** may appear as bare strings — coerce each to a structured dependency edge keyed by the referenced step id.
  - **integration_checks** arrive as objects `{id, assert, status}` — preserve all three fields per check; never collapse to a status flag.
  - **traces_to** links carry requirement-coverage intent — retain them verbatim for coverage closure downstream.
  - **Plan-level fields** — `gate_status`, `blocking_defects`, `structural_faults`, `build_order`, `refinement_back_edges` — capture each into structured metadata.

3. **Consume every metadata field — no field silently dropped.** Walk the full plan and every step. Each field present in the source must land either in `normalized_plan` (step-level structure: id, dependencies, inputs, outputs, acceptance_criteria, integration_checks, traces_to, actions/commands) or in `plan_metadata` (plan-level structure: gate_status, blocking_defects, structural_faults, build_order, refinement_back_edges, verdict, and any plan-scope annotations). If a field has no home, that is a dialect failure — see failure modes.

4. **Normalize without interpreting.** Coerce shapes, but do not honor gates, compute a schedule, or evaluate DoD here — those belong to `honor_gates`, `schedule_steps`, and `verify_dod`. Your job ends at a faithful, structured representation.

5. **Write outputs.** Produce exactly:
  - `normalized_plan` — the normalized step graph with all step-level fields preserved and dependencies/integration_checks/traces_to in structured form.
  - `plan_metadata` — the plan-level metadata block (gate_status, blocking_defects, structural_faults, build_order, refinement_back_edges, verdict, source-form provenance).

## Failure modes (fail closed)

- **Unknown dialect.** If the artifact is neither recognizable emitted JSON nor normalizable Markdown, or contains a field/shape no adapter covers, HALT and report the unrecognized structure. Never guess or coerce blindly past an unknown shape.
- **Silent field loss.** If any source field cannot be placed into `normalized_plan` or `plan_metadata`, treat it as a dialect failure and HALT rather than discard it.
- **Markdown that does not normalize.** If Markdown cannot be losslessly mapped to the JSON shape, HALT — do not emit a partial `normalized_plan`.
- **Structural inconsistency.** If a dependency references a step id absent from the plan, or build_order disagrees with the declared step set, surface it in `plan_metadata` and HALT for resolution; do not repair silently.

## Output contract
Write exactly: `normalized_plan`, `plan_metadata`. No additional outputs.
