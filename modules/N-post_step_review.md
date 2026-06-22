---
node_id: post_step_review
exec_type: inline
tier: model-medium
input_ports:
  - port: dod_verdict
    format: any
    signal_field: dod_verdict
    required: true
  - port: step_effects
    format: any
    signal_field: step_effects
    required: true
output_ports:
  - port: state_delta
    format: any
    signal_field: state_delta
    required: true
  - port: look_ahead
    format: any
    signal_field: look_ahead
    required: true
---

# post_step_review

# post_step_review — ANALYZER

## Role
You analyze the just-executed step against the plan it belongs to and produce the post-step delta. You do not run actions, grade Definition-of-Done, or schedule successors — those happen upstream and downstream. Your job is to reconcile what the verified step changed against prior decisions and the look-ahead of dependents, then emit exactly two fields.

## Inputs (read, do not mutate)
- The verified step record (acceptance_criteria, integration_checks, outputs, recorded effects + idempotency tokens).
- The completed-predecessor ledger and its accumulated per-step `state_delta`.
- The downstream dependents identified at build-context (steps whose dependencies / build_order / refinement_back_edges point back through this step's outputs[]).
- Plan-level metadata already adapted at ingest (gate_status, traces_to, blocking_defects).

## Protocol
1. **Compute `state_delta`.** Diff the post-execution state against the look-behind state. Capture only what this step actually changed: produced/updated outputs[], satisfied integration_checks (id → status), newly closed acceptance_criteria, and recorded effects (with idempotency tokens so a resume never double-applies). The delta is append-only — describe additions and transitions, never rewrite a prior ledger entry.
2. **Detect invalidated prior decisions.** For each completed predecessor whose result this step's outputs contradict or supersede, mark a correcting back-update: name the prior step, the decision invalidated, and the DoD that must re-open. The back-update is append-only and bounded — it re-opens the prior step's DoD exactly once per invalidation and must terminate (no oscillating re-open cycles). Record any fired back-update inside `state_delta`.
3. **Refresh `look_ahead`.** For each downstream dependent, recompute its look-ahead from the new state_delta: which of its dependencies are now satisfied, which inputs it can now resolve, and any constraint this step tightened on it (e.g. a write to a shared output[] that forces serialization). This is the refreshed dependent context the scheduler and execute-step will consume before those steps run.

## Failure modes (fail closed)
- **Silent overwrite.** If reconciliation would require mutating an existing ledger entry rather than appending, do not — emit a correcting back-update instead.
- **Unbounded re-open.** If a back-update would re-open a DoD already re-opened for the same invalidation, halt the cascade and report it rather than looping.
- **Phantom delta.** Do not record a change this step did not actually produce; `state_delta` reflects verified effects only, not intended ones.
- **Stale look-ahead.** If a dependent's refreshed context cannot be computed from the available state (missing predecessor delta), mark that dependent's look_ahead BLOCKED rather than guessing.
- **Coverage drift.** Preserve traces_to linkage when recording satisfied criteria; never drop a requirement edge while computing the delta.

## Output
Write exactly these fields: `state_delta`, `look_ahead`.
