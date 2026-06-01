# epiphany-executor — forge brief (S-P0-forge)

A tier-3 goatcs-harness skill that ingests an **epiphany-plan execution plan** (the real
emitted JSON, or epiphany-plan Markdown normalized to it) and **executes that plan step by
step** to produce the implemented solution — bounded, verified, checkpointed, recoverable.

It reuses the goatcs-harness substrate (append-only ledger with per-step state_delta, Burr
SQLite checkpoint, the per-step fidelity gate, and run --resume / --fork-from-seq /
handoff) and never reimplements them. The skill compiles each plan into a harness graph
(one plan step = one node = one checkpoint) and the harness runtime drives it.

The executor's core job is **dependency-aware scheduling and verified step execution**:
it reads a plan's steps, computes a **schedule** (a safe execution order over the
dependency graph), then runs and verifies each scheduled step in turn.

## The executor's own driver pipeline (nodes)

1. **ingest-plan** — read the plan; consume every metadata field (no field silently
   dropped); adapt the actual emitted shape (bare-string dependencies, integration_checks
   object {id,assert,status}, traces_to, plan-level gate_status/blocking_defects/build_order/
   refinement_back_edges) via tolerant field adapters; fail closed on unknown dialect.
2. **honor-gates** — read plan-level gate_status, blocking_defects, structural_faults, and
   per-step integration_checks.status; HALT for human resolution if the plan declares itself
   not execution-ready (verdict != PASS, open blocking defect, or a BLOCKING-defect step).
3. **build-context** — assemble per-step look-behind (completed predecessors + ledger
   state_delta) and look-ahead (downstream dependents); keep the whole plan + completed
   ledger resident when it fits, stream with bounded windows when it does not.
4. **schedule-steps** — **scheduling is the executor's central responsibility.** Build the
   dependency DAG from each step's dependencies plus the plan's build_order, then compute a
   **schedule**: the order in which steps become ready to run. The scheduler respects all
   dependency edges and refuses to reorder across write-write conflicts on outputs[]; it is
   conservative and fail-closed (serialize unless independence is provable). Scheduling
   decides which step the executor runs next.
5. **execute-step** — run the next scheduled step: classify each command's effect_class
   before running it; preview the resolved inputs, pulled context, DoD, and intended
   side-effects; perform the step's actions; record effects with idempotency tokens;
   irreversible effects pass a pre-commit checkpoint + human gate.
6. **verify-dod** — Definition-of-Done = acceptance_criteria + integration_checks + outputs,
   evaluated at the harness fidelity gate by an independent verifier (the step's executor may
   not grade its own work); empty acceptance_criteria => BLOCKED, never auto-passed.
7. **post-step-review** — compute state_delta; on an invalidated prior decision fire an
   append-only correcting back-update that re-opens the prior step's DoD (bounded/terminating);
   refresh successors' look-ahead before they run.
8. **checkpoint-route** — append to the ledger; advance lifecycle
   UNSTARTED -> IN_FLIGHT -> VERIFIED -> ACCEPTED; return to scheduling for the next ready step.
9. **coverage-and-report** — maintain requirement-coverage closure (traces_to); emit a
   telemetry/health view and a resume cold-start brief; produce the executed result.

A failed verify routes back to recovery (halt + checkpoint + recovery/rollback offer; the
step is never marked complete on failure). The run is recoverable from ledger + checkpoint
without double-applying committed effects.

## Honored constraints
JSON-primary input; full-metadata consumption; per-step fidelity verification; reuse the
harness substrate (do not reinvent ledger/checkpoint/fidelity-gate/resume); bounded/verified/
checkpointed/recoverable reliability envelope (not literal zero-fault); ship a focused skill,
no general-purpose workflow-engine sprawl.
