---
name: epiphany-executor
description: Executes an epiphany-plan execution plan step by step on the goatcs-harness runtime — bounded, verified, checkpointed, recoverable. Ingests the real emitted plan JSON (or epiphany-plan Markdown), compiles each step into a harness node (one step = one node = one checkpoint), schedules ready steps, runs and verifies each at the fidelity gate with an independent verifier, then back-updates invalidated prior work and propagates forward deltas. Honors plan-declared gates/defects (halts when the plan says it is not execution-ready). Reuses the harness ledger / Burr checkpoint / fidelity gate / resume-fork-handoff; never reimplements them.
---

# epiphany-executor

The third skill in the pipeline **epiphany-spec → epiphany-plan → epiphany-executor**.
epiphany-plan emits a structured plan; **epiphany-executor executes it** to produce the
implemented solution.

## INVOCATION

```
# execute a real epiphany-plan JSON run:
goatcs-harness run <epiphany-executor>/graph.json --seed plan_path=<plan.json>

# serial fallback (disables wave parallelism, AX-01):
... --serial

# resume / fork / handoff (reused harness substrate, INV-3):
goatcs-harness run --resume <session_dir>
goatcs-harness fork <session_dir> --at-seq <n>
goatcs-harness handoff <session_dir> --from claude --to codex
```

The executor consumes the **actual emitted shape** (bare-string `dependencies`,
`integration_checks` object `{id,assert,status}`, `traces_to`, plan-level `gate_status` /
`blocking_defects` / `build_order` / `refinement_back_edges`) via tolerant adapters (INV-18),
and **halts** when a plan declares itself not execution-ready (INV-17).

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
