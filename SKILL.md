---
name: epiphany-executor
description: Executes an epiphany-plan execution plan step by step on the goatcs-harness runtime — bounded, verified, checkpointed, recoverable. Ingests the real emitted plan JSON (or epiphany-plan Markdown), compiles each step into a harness node (one step = one node = one checkpoint), schedules ready steps, runs and verifies each at the fidelity gate with an independent verifier, then back-updates invalidated prior work and propagates forward deltas. Honors plan-declared gates/defects (halts when the plan says it is not execution-ready). Reuses the harness ledger / Burr checkpoint / fidelity gate / resume-fork-handoff; never reimplements them.
---

# epiphany-executor

The third skill in the pipeline **epiphany-spec → epiphany-plan → epiphany-executor**.
epiphany-plan emits a structured plan; **epiphany-executor executes it** to produce the
implemented solution.

## HOW IT WORKS

The executor transforms a plan into a **deterministic runtime graph** (13 harness nodes, 16 edges) via the COMPILE model: each plan step becomes one graph node, one checkpoint, and one Burr action. The graph loops through `schedule_steps → execute_step → verify_dod → checkpoint_route` (back-edge at E11, capped at 200 retries) to iteratively execute ready steps, verify their outputs with an independent verifier, then advance to the next step or halt if a gate fails. A built-in HITL gate (`human_gate`) blocks on uncertain outcomes, never auto-progressing.

## INVOCATION

You **DRIVE THIS GRAPH** — you do not re-implement its methodology by hand. `--provider inline`
genuinely drives the 13-node executor graph: the deterministic nodes (`read_plan` → `fs.read_text`,
`ingest_plan` → `plan.normalize_md`, `closure_gate` → `wiring.closure_gate`) run as CODE, and the
reasoning nodes (`honor_gates`, `build_context`, `schedule_steps`, `execute_step`, `precommit_gate`,
`verify_dod`, `post_step_review`, `checkpoint_route`, `coverage_and_report`) PAUSE at exit-11 for you
to reason, one at a time, then resume. The graph forces the sequence — that ordering *is* the
enforcement (you cannot reach `closure_gate` without driving execute→verify_dod→checkpoint per step).

```
# 1. write a seed FILE (note: --seed takes a JSON FILE, NOT key=value):
echo '{"plan_path": "<abs/plan.json>"}' > <out>/seed.json
#    convenience: python <epiphany-executor>/bootstrap.py prepare <abs/plan.json> --out <out>
#    writes <out>/seed.json AND prints the exact drive command below.

# 2. drive the executor graph inline. --read-dir MUST include the plan's directory (else read_plan's
#    fs.read_text is sandboxed out and the run goes UNCERTAIN at node 1):
goatcs-harness run <epiphany-executor>/graph.json --seed <out>/seed.json --provider inline \
    --read-dir <plan-dir> --scratch-dir <out>/session

# 3. at each exit-11 pause: read the node's modules/N-*.md contract, produce its declared outputs,
#    submit, then resume — repeat to coverage_and_report → closure_gate:
goatcs-harness submit <node> --session <out>/session --inline --outputs <out>/<node>.json
goatcs-harness run <epiphany-executor>/graph.json --resume <out>/session --provider inline --read-dir <plan-dir>

# resume / fork / handoff (reused harness substrate, INV-3):
goatcs-harness run <epiphany-executor>/graph.json --resume <session_dir> --provider inline --read-dir <plan-dir>
goatcs-harness fork <session_dir> --at-seq <n>
goatcs-harness handoff <session_dir> --from claude --to codex
```

> **At `execute_step`** (the per-step pause) you do the actual build work for that one step (TDD,
> commands, effects) and emit `step_effects`/`effect_records` as evidence. **At `verify_dod`** you
> adopt the independent-verifier lens (re-derive the DoD from that evidence, never your execute
> narration). Driving the graph is what makes verify_dod a SEPARATE act from execute_step — that
> separation is lost the moment you hand-emulate the loop instead of driving it.

The executor consumes the **actual emitted shape** (bare-string `dependencies`,
`integration_checks` object `{id,assert,status}`, `traces_to`, plan-level `gate_status` /
`blocking_defects` / `build_order` / `refinement_back_edges`) via tolerant adapters (INV-18),
and **halts** when a plan declares itself not execution-ready (INV-17).

## INLINE OPERATING CONTRACT — mandatory under `--provider inline`

**The primary, enforced path is to DRIVE THE GRAPH** (INVOCATION above): `goatcs-harness run … --provider
inline` + the submit/resume loop. Driving the graph IS the enforcement — the harness routes the node
sequence, runs the deterministic gate/IO nodes (`read_plan`/`ingest_plan`/`closure_gate`) as CODE, and
pauses at exit-11 at each reasoning node for you. Do NOT silently re-implement the loop in your head: a
hand-emulated run loses `verify_dod`'s separation-from-`execute_step` and never runs the closure node.

If you ever cannot drive the graph (e.g. the harness is unavailable), the **fallback emulation** is
binding and MUST still run the same tested gates as CODE at the boundaries — never re-derive them by
hand:
1. **Start gate.** `python <skill>/bootstrap.py scaffold <plan.json> --session <dir>` → writes a
   per-step DoD checklist (`<dir>/.executor-session/steps.jsonl`: each step's acceptance_criteria +
   integration_checks + outputs, with `dod_evidence`/`dod_verdict` slots) and runs the REAL
   `coverage` gate. **Exit 3 / `start_gate: BLOCKED`** ⇒ an executor-caused orphan or an
   empty-acceptance step — resolve it before executing; never proceed past a BLOCKED start gate.
   (When driving the graph this is the `honor_gates`/`coverage_and_report` nodes; emulation calls the
   same modules directly.)
2. **Honor plan gates** (INV-17): if the plan declares itself not execution-ready
   (`gate_status`/`blocking_defects`), halt and surface — do not build.

**Per-step loop (every step — whether driven by the graph's `execute_step`↔`verify_dod` nodes or
emulated):**
- **Classify effects before acting** (pure / reversible / irreversible). An irreversible or
  outward-facing effect is GATED — pre-commit checkpoint + human confirm, never on your own authority.
- **Execute** (TDD: failing test → minimal impl → green), recording evidence (the commands run + their
  output), not just a claim.
- **Verify DoD in a role-separated verifier lens** (A.4 / `verify_dod`): re-derive each
  acceptance_criterion + integration_check + output from the recorded **evidence/effect records**,
  never from your own build narration. Empty acceptance_criteria ⇒ **BLOCKED**, never auto-pass. A
  criterion you cannot ground in independent evidence ⇒ FAILED (or UNCERTAIN→appendix), never a PASS.
  Fill the step's `dod_evidence`/`dod_verdict` in `steps.jsonl`.
- **Checkpoint** the step (git commit) before advancing. A FAILED DoD halts + offers recovery; the
  step is never marked complete (INV-1).
- **If the step authored/edited a `graph.json`,** the RL-1 runtime-liveness DoD below is
  ADDITIONALLY mandatory (drive the router; module-present ≠ control-flow-live).

**Closure (end of run — the anti-false-green teeth):**
- Run the REAL closure gate, do not emulate it: `python <skill>/bootstrap.py close <plan.json>
  --session <dir> --skill-pkg <built-skill-dir>`. It runs `goatcs-harness wiring-check` (with the $0
  smoke) against the skill's authored `wiring-contract.yaml` (or a bootstrapped fallback) + the
  coverage-with-closure report. **`route: closure-blocked`** with a gap-list is a recovery item routed
  back into the build loop, exactly like a failed DoD — never a silent pass.
- **Spawn a fresh-context verifier sub-agent for the final ship-gate/closure DoD** (Agent tool). Same
  model, but a clean context that never saw your build reasoning — it re-derives the ship verdict from
  the artifacts + the gate outputs alone. Self-grading the final gate is the erv3 false-green class;
  for the run's terminal acceptance, genuine context-separation is required, not just a verifier lens.

**Provenance:** keep a human-readable ledger (`<dir>/.executor-session/ledger.md`) of per-step
state + decisions, and surface genuine design ambiguities to the operator (interactive — design
decisions are operator-led; only the approved+audited build runs autonomously).

## ARCHITECTURE — COMPILE model

The fixed artifact = an **epiphany-plan importer** + **per-node contract templates** +
this SKILL.md. At import, the executor **compiles each plan into a harness graph**: one plan
step → one harness node → one Burr action → one checkpoint. Every compiled node is stamped
with the four binding contract field-groups (`epiphany_executor/contract_template.py`):
**lifecycle · DoD · effect · traces** (see `docs/contract-template.md`).

The driver pipeline (`graph.json`): `read_plan → ingest_plan → honor_gates → build_context →
schedule_steps → execute_step → precommit_gate → verify_dod → post_step_review →
checkpoint_route → coverage_and_report`, with the per-step loop back-edge
`checkpoint_route → schedule_steps`.

## AI / MACHINE-ADVANTAGE MODES (A.1–A.9)

Every lever is **safety-bounded**: parallelism only over output-disjoint, worktree-isolated,
non-irreversible, statically-provable steps; all gains stay inside the
verified/checkpointed/recoverable envelope.

- **A.1 Wave-parallel fan-out** — each dependency-DAG antichain is split into a parallel-eligible
  cohort (pairwise output-disjoint, no irreversible effect, no shared external resource), one
  effector sub-agent per step in its own git worktree. **Atomic wave:** the whole cohort is
  verified at a barrier and fast-forwarded only if it ALL passes; a mid-wave fail discards the
  staged worktrees (pre-wave checkpoint stands). `--serial` = width-1.
- **A.2 Thinking-budget allocation** — reasoning depth scales with blast-radius / reversibility /
  fan-out / defect-proximity; never down-tiers a step out of a gate.
- **A.3 1M-context hold-all** — full plan + completed ledger resident while it fits; tiered
  summaries then bounded-window streaming above budget.
- **A.4 Isolated-context adversarial verification + jury** — DoD verification runs in a fresh
  verifier sub-agent that never sees the effector's reasoning (anti-self-grading); high-stakes
  steps escalate to an N-way any-veto jury.
- **A.5 Speculative dry-run look-ahead** — preview the next K steps in throwaway worktrees
  (irreversible effects stubbed) to refine the disjointness test; advisory only.
- **A.6 Background tasks + Workflow compilation** — long actions run as background Tasks joined
  at the barrier; a fully-resolved DAG may compile to a deterministic Workflow.
- **A.7 Cross-run memory flywheel** — each run distills failure signatures / effect corrections /
  budget calibration / plan-shape priors into Memory; advisory, never relaxes a gate.
- **A.8 Worktree isolation** — every parallel/speculative effector runs in its own git worktree;
  accepted steps merge in deterministic `build_order`; a conflict demotes to serial.
- **A.9 Background ledger sentinel** — after each barrier a background agent re-asserts all
  PASSED steps' integration_checks against current state; on regression it appends a forward-delta
  and raises a 1-firing back-edge — never blocks the active wave.

## RUNTIME-LIVENESS DoD — mandatory for plans that BUILD a harness graph/skill (RL-1)

*Added 2026-06-10 after a build whose green ship gate (`verify` + `wiring-check` + tests) shipped
**two BLOCKING runtime bugs** — an interview loop that dead-locked on turn 1 and an AND-join that
never gated. Root cause: per-step DoD checked module wiring + acceptance prose, and the `$0` smoke
**pauses at the first reasoning/HITL node**, so nothing downstream is ever driven. Module-present ≠
control-flow-live.*

When a step authors or edits a `graph.json` (nodes, edges, gates, joins, loops), its DoD is **NOT
satisfied** by `verify`/`wiring-check`/unit tests alone. It MUST additionally **drive the router
over mid-run state** and confirm:
- **No dead-lock on first arrival.** For every node whose out-edges are *all* gated, drive
  `route.choose_successor(spec, node, state)` with a realistic first-arrival state — expect a real
  successor, never `dangling`. (Especially loop nodes: a gate signal produced only by the loop's
  re-entry/back-edge is `None` on turn 1 → all gates false → halt. Seed it on the forward spine.)
- **Joins actually wait.** For every `and_join_group` convergence, drive `route.join_ready` with
  ONE branch done (expect not-ready) and ALL done (expect ready). A join node with no `join_policy`
  is inert — fix it.
- **Run the liveness lints.** `verify` now emits `andjoin-without-policy` and
  `loop-signal-grounding` (both WARN) for exactly these two failure classes — treat them as
  **step-blocking** for a graph-building step, not advisory.
- **Reject self-grading (A.4 is mandatory here).** This DoD check runs in a **fresh isolated
  verifier** that never saw the authoring reasoning — these bugs survive precisely because the
  author "knows it's wired." Drive the router; don't reason about it.

This is the control-flow analogue of *verify-integration-not-just-modules*: integration includes
**runtime liveness**, not only "the binding resolves."

## EDGE CASES / RELIABILITY

- A failed DoD → **halt + checkpoint + recovery/rollback offer**; the step is never marked
  complete (INV-1, R-023).
- Empty `acceptance_criteria` → **BLOCKED**, never auto-passed (INV-10).
- Externally-irreversible effects without a server-side idempotency token are **GATED** (human
  confirm, no auto-resume) in v1 (INV-13); auto-resume is a v2 effect-ledger capability.
- A back-update appends a **correcting delta** (never mutates history, INV-6) and is bounded
  (INV-7); undoing an irreversible effect is forbidden → human-review item.
- Plan drift on a started step → halt + human reconciliation (§5.6).

---
*Forge provenance: authored by `goatcs-harness forge --profile power` (GoT-basic, best-of-3);
topology corrected + contracts hand-authored in S-P0-contracts. Regenerable via the
non-clobber re-forge path (`tools/reconcile_forge.py`).*
