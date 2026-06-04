# AGENTS.md — epiphany-executor (agent operating guide)

Cross-ref: `SKILL.md` (the harness-loaded skill contract) and `README.md` (full human+AI
reference). This file is the **agent-facing** quick guide. Everything here is grounded in the
source; see the verification table in `README.md §11`.

---

## 1. TL;DR for agents

`epiphany-executor` is the **final pipeline stage**: `epiphany-spec → epiphany-plan →
epiphany-executor`. It ingests an epiphany-plan execution plan (JSON, or its Markdown) and executes
it **one step at a time** on the goatcs-harness runtime — bounded, DoD-verified, checkpointed,
recoverable. **COMPILE model:** one plan step → one harness node → one Burr action → one checkpoint.

You (the agent) reason at each node; the **harness owns routing** — it picks the next node from the
signals you emit. You do not choose successors and you do not self-resolve human gates. The driver
loops `schedule_steps → execute_step → precommit_gate → verify_dod → post_step_review →
checkpoint_route` (back-edge to `schedule_steps`) until every step is ACCEPTED, then exits at
`coverage_and_report`.

It **reuses** the harness substrate (ledger / Burr checkpoint / fidelity gate / resume-fork-handoff)
and never reimplements it. Above the harness, the node bodies call a deterministic Python layer
(`epiphany_executor/*.py`) for scheduling, DoD, census, lifecycle, etc.

---

## 2. Invocation contract

```bash
goatcs-harness run <epiphany-executor>/graph.json --seed plan_path=<plan.json>
#   --serial            disable wave parallelism (every wave width 1)
#   --provider codex    dispatch reasoning to Codex for heavy harness/forge steps
#   goatcs-harness run --resume <dir>            resume a halted/paused session
#   goatcs-harness fork <dir> --at-seq <n>       branch a new session from a seq
#   goatcs-harness handoff <dir> --from claude --to codex
```

**Seed:** `plan_path` (the only seed input; `graph.json:14-21`, `modules/N-read_plan.md`). Markdown
plans are normalized at `ingest_plan` (`plan.normalize_md`), so `plan_path` may point at JSON or MD.

**What each terminal looks like:**

| state | how it presents |
|---|---|
| **done** | run exits at `final_node == "coverage_and_report"`; `schedule_status == "complete"`; coverage closure + telemetry + resume brief + executed result emitted |
| **HITL pause** | `final_node == "human_gate"`, harness verdict `UNCERTAIN`, `awaiting_human`; resolve with `goatcs-harness override --session <dir> --node human_gate --values '{"human_decision":"approve"}'` then `run --resume` |
| **HALT (start gate)** | `honor_gates` emits `gate_decision = HALT` with enumerated triggering signals; nothing downstream runs (INV-17) |
| **HALT (blocked schedule)** | `schedule_status == "blocked"` has no out-edge → run halts for human resolution (fail-closed) |
| **step FAILED** | step stays `IN_FLIGHT`/`FAILED`, never ACCEPTED; recovery menu offered (INV-1) |

**Lifecycle states (per step):** `UNSTARTED → IN_FLIGHT → VERIFIED → ACCEPTED` (terminal success);
plus `BLOCKED`, `FAILED`, `AMENDED`, `AWAITING`. Run-level aggregate: `PARTIAL`.

---

## 3. Decision rules

- **Serial vs wave.** Default is wave-parallel; a step joins a parallel cohort **only if** provably
  output-disjoint + statically non-irreversible + has declared outputs + no shared external
  resource. Anything unprovable → serial (fail-closed). No declared `outputs[]` ⇒ conflicts-with-all
  ⇒ forced serial. Use `--serial` when you need the boring deterministic baseline or are debugging.
- **When a step routes to `human_gate`.** `precommit_gate` sets `needs_human = true` for: a §6 marker
  (OQ-1, refusal trigger, plan-review gate S-G2, `human.final_gate` S-G14, §9-assumption-falsified),
  a high-stakes irreversible effect, **or** a non-empty `step_context.self_clobber_paths`
  (self-modifying plan writing into a live dir). You present context to the human; you do NOT submit
  `human_gate`.
- **Codex for heavy harness/forge steps.** When the plan is `target_profile == "harness-forge"`,
  `context_builder` injects a `provider-hint: --provider codex` line — claude-cli times out on large
  graphs. Dispatch heavy forge/harness runs to Codex.
- **Thinking tier.** `allocate_thinking_tier` is raise-only and never down-tiers a step out of a gate;
  irreversible / unknown-effect / defect-adjacent / high-fan-out → DEEP. Memory priors may only raise.

---

## 4. Operating invariants for agents (do not violate)

1. **Don't self-grade.** `verify_dod` is an independent verifier. Under `--provider inline` (same
   agent reasons every node) independence is enforced by **ROLE separation**: re-derive each DoD
   predicate from the step's `effect_records`/evidence, never from the executor's own narration. A
   verdict you cannot ground in independent evidence is UNCERTAIN→appendix, never an auto-PASS
   (`modules/N-verify_dod.md:49`).
2. **Every plan field must have a census consumer.** If you add a field to a plan, add a
   `census.py` consumer (or `metadata-only` waiver) — otherwise the census BLOCKs by design (INV-2).
3. **Never bypass a blocking defect / gate.** `honor_gates` HALT, `verify_dod` BLOCKED/FAILED,
   `precommit_gate` refusal, census BLOCK, drift HALT — none of these are advisory. Do not "work
   around" them; route to recovery / human (INV-1, fail-closed everywhere).
4. **Append-only, bounded, never undo irreversible.** History is append-only (INV-6); back-updates
   are bounded and terminate (INV-7); undoing an externally-irreversible effect is forbidden →
   human-review item. No ACCEPTED step re-runs on resume (INV-5).
5. **Empty acceptance ⇒ BLOCKED.** Never synthesize acceptance criteria to make a step pass (INV-10).

---

## 5. Common agent mistakes

- **Adding a plan field with no census consumer** → census `BLOCK-unconsumed`. Fix: add a consumer
  entry in `epiphany_executor/census.py` (`PLAN_LEVEL_CONSUMERS` / `STEP_LEVEL_CONSUMERS`) or an
  explicit `metadata-only` waiver. Do not delete the census check.
- **Out-dir overlap** — pointing plan outputs into a live install dir while the plan is
  `self_modifying`. This trips the self-clobber guard (`needs_human`). Redirect to an explicit safe
  `out_dir` in the harness_forge pack; don't disable the guard.
- **Treating a HITL pause as failure.** `human_gate` is a designed stop, not an error. Resolve via
  `override` + `run --resume`; do not retry the whole run or mark it failed.
- **Self-clobber when outputs hit live dirs.** Writing into `~/.claude/skills`,
  `~/projects/goatcs-harness`, or `~/projects/epiphany-*` in place can overwrite the running
  executor/harness/forge. Emit to a sandbox/out-dir; the guard exists to catch exactly this.
- **Emitting `complete` to escape a stall.** `schedule_status == complete` means EVERY step is
  ACCEPTED. A stall is `blocked` (surface the blocking predecessors), never `complete`.
- **Reordering / "cleaning up" the raw plan at `read_plan`.** It is a byte-faithful pass-through;
  normalization belongs to `ingest_plan` (`modules/N-read_plan.md:42`).

---

## 6. Machine-readable quick reference

```yaml
nodes:                       # 12 (graph.json)
  io_no_llm:   [read_plan, ingest_plan, human_gate]   # human_gate is hitl:true
  llm_medium:  [honor_gates, build_context, schedule_steps, execute_step,
                precommit_gate, verify_dod, post_step_review, checkpoint_route,
                coverage_and_report]
entrypoint: read_plan
seed: { plan_path: <path to plan.json or plan.md> }

driver_pipeline: read_plan -> ingest_plan -> honor_gates -> build_context -> schedule_steps
per_step_loop:   schedule_steps -> execute_step -> precommit_gate -> verify_dod
                 -> post_step_review -> checkpoint_route -> (back-edge E11) schedule_steps
exit:            schedule_steps --(schedule_status==complete)--> coverage_and_report

routing_signals:                         # harness routes on these; agent does not pick successor
  schedule_status: [ready, complete, blocked]   # ready->execute_step; complete->coverage; blocked->HALT
  needs_human:     [true, false]                # true->human_gate (E13); false->verify_dod (E07)
back_edge: { id: E11, from: checkpoint_route, to: schedule_steps, retry_cap: 200 }

per_step_gates:
  honor_gates(start):   evaluate_gate(plan) -> HALT | PROCEED          # INV-17, once
  execute_step:         classify_command before run                    # INV-15
  precommit_gate:       checkpoint + idempotency-token + verified + PASS-scope; sets needs_human
  verify_dod:           DoD = acceptance ∪ integration_checks ∪ outputs; PASS|FAILED|BLOCKED
  checkpoint_route:     append ledger + bind Burr + advance one lifecycle stage

census_consumers:        # authority = epiphany_executor/census.py
  plan_level:  [plan_id, title, source_spec, gate_status, blocking_defects,
                non_blocking_observations, requirement_preservation, build_order, steps,
                structural_faults, refinement_back_edges, schema_version,
                target_profile, harness_forge]            # last two = harness/forge (schema-tolerant)
  step_level:  [step_id, goal, actions, inputs, outputs, dependencies, integration_checks,
                acceptance_criteria, traces_to, traces_requirements, phase,
                refinement_back_edges, emit_note, gap_surfaced, is_gap_marker,
                resolved_bindings, target_subsystem, obligation_class]
  verdicts:    [CONSUMED, WAIVED, SCHEMA-TOLERANT, BLOCK-unconsumed, BLOCK-stale-binding]

lifecycle_states:        [UNSTARTED, IN_FLIGHT, VERIFIED, ACCEPTED, BLOCKED, FAILED, AMENDED, AWAITING]
recovery_options:        [retry, rollback, fork, skip-with-waiver, halt-for-human]
                         # rollback only if NOT externally-irreversible; skip only if downstream-safe
halt_classes:            [defect-ack, drift, irreversible, waiver-ack, backupdate-budget]
```

---

## 7. Self-verification checklist (before declaring a run done)

- [ ] `honor_gates` PROCEEDed (or the HALT was the correct, expected outcome).
- [ ] Every step reached `ACCEPTED` via an independent `verify_dod` PASS (no self-graded steps).
- [ ] No step with empty acceptance was auto-passed (those are BLOCKED).
- [ ] `schedule_status == complete` was emitted only because EVERY step is ACCEPTED.
- [ ] Final node is `coverage_and_report`; coverage closure has no executor-caused orphan.
- [ ] No census BLOCK (every plan/step field bound or waived).
- [ ] Any `needs_human` halt was resolved by a human `override`, not self-resolved.
- [ ] Resume brief is self-contained (open holes, failed/blocked steps, pending gates surfaced).

---

## 8. Integration for agents

- **Consuming `plan_meta.harness_forge`.** When `plan_meta.target_profile == "harness-forge"`,
  `ingest_plan` lifts `target_profile` + the `harness_forge` pack into `plan_metadata`;
  `build_context` mirrors `context_builder.build_step_context(..., plan_meta=plan_metadata,
  step=<raw step>)` to attach harness/forge context lines and raise the tier (advisory). For
  `generic` plans, add none of this — context is byte-identical.
- **The self-clobber guard.** A `self_modifying` plan whose step `outputs[]` resolve into a live
  install dir (`~/.claude/skills`, `~/projects/goatcs-harness`, `~/projects/epiphany-*`) without an
  explicit `out_dir` → `needs_human` at `precommit_gate`. Redirect to an out-dir or get human
  confirmation. Path-prefix match + `out_dir` exemption (a `/tmp/out/...` path that merely contains a
  live token is NOT flagged).
- **`provider_hint = codex`.** Surfaced by `harness_forge_context_lines` for heavy harness/forge
  runs; honor it (claude-cli times out on large graphs). Exit-code conventions to know: **exit-7** =
  static gate fail, **exit-11** = inline reasoning pause.

---

## 9. Pointers

- `SKILL.md` — the harness-loaded skill contract (HOW IT WORKS, INVOCATION, A.1–A.9, edge cases).
- `README.md` — full human+AI reference (architecture, Python layer, invariants, verification table).
- `docs/contract-template.md` — the per-node COMPILE contract field-groups + tolerance/fail-closed.
- `docs/BUILD-COMPLETE.md` — build DoD, where it lives, co-deliverables, INV-12 status.
- `docs/INV-12-cotuning-tracker.md` — the cross-skill co-tuning ledger (no silent bypasses).
- `docs/handoff-epiphany-plan-reconciliation.md` — the epiphany-plan schema↔emitter handoff.
- **Pipeline contract:** `~/docs/epiphany/harness-forge-pipeline-integration.md` — the single source
  of truth for `target_profile`, the context-pack, and back-compat rules across all three stages.
- `tools/selfhost.py` — dogfood (executor runs its own build plan, INV-12); `tools/v_battery.py` —
  post-emit re-verify gate; `tools/reconcile_forge.py` — non-clobber re-forge.
