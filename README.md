# epiphany-executor

> Executes an epiphany-plan execution plan **step by step** on the goatcs-harness runtime — bounded, verified, checkpointed, recoverable.

**Version:** `1.0.0` (`epiphany_executor/__init__.py:10`, `pyproject.toml:8`, `graph.json:6`)
**Audience:** humans operating the pipeline AND AI agents driving the harness (see also `AGENTS.md`, `SKILL.md`).

---

## 1. What it is

`epiphany-executor` is the **third and final stage** of the pipeline:

```
epiphany-spec  →  epiphany-plan  →  epiphany-executor
   (spec)          (step-DAG)         (executed solution)
```

epiphany-plan emits a structured execution plan (JSON, or its default Markdown); epiphany-executor
**ingests that plan and executes it**, one step at a time, to produce the implemented solution. It
does not re-plan and it does not re-spec — it executes a committed plan under verification and
checkpointing.

It is a **forge-emitted goatcs-harness skill**: a `graph.json` + per-node module bodies
(`modules/N-*.md`) + `SKILL.md`, authored by `goatcs-harness forge --profile power` and then
topology-corrected with hand-authored contracts (`SKILL.md:91-93`, `provenance.json`,
`RATIONALE.md`). Above the harness it ships a hand-authored Python layer (`epiphany_executor/`)
that the node bodies invoke for the deterministic, testable parts (scheduling, DoD, census,
lifecycle, …). It **reuses** the harness substrate — ledger, Burr checkpoint, fidelity gate,
resume/fork/handoff — and never reimplements it (`epiphany_executor/__init__.py:1-8`).

### The COMPILE model

The fixed artifact is an **epiphany-plan importer + per-node contract templates + this graph**.
At ingest the executor **compiles the plan into the runtime**:

> **one plan step → one harness node → one Burr action → one checkpoint**

Every compiled node is stamped (`epiphany_executor/contract_template.py:90`,
`stamp_node_contract`) with four binding contract field-groups
(`contract_template.py:36`, `docs/contract-template.md`):

| field-group | shape | consumed by |
|---|---|---|
| **lifecycle** | `{state, history[]}`; starts `UNSTARTED` | lifecycle state machine (`lifecycle.py`) |
| **dod** | `{acceptance_criteria[], integration_checks[], outputs[], verifiable}` (DoD = the union, spec §2) | DoD verifier at the harness fidelity gate (`dod.py`) |
| **effect** | `{effect_class, footprint:{declared_outputs[], conflicts_with_all}}` | scheduler reads static footprint; `effect_class.py` sets the concrete class pre-execution |
| **traces** | `traces_to` / `traces_requirements` | coverage closure (`coverage.py`) |

The importer is **shape-tolerant** (INV-18, `contract_template.py:16-23`): it accepts both the real
emitted shape (bare-string `dependencies`, `integration_checks` objects `{id,assert,status}`,
`traces_to`) and the `plan.schema.json` shape, and never drops an unknown key (preserved under
`extra`).

---

## 2. When to use / not use

**Use it when:**
- You have an epiphany-plan execution plan (JSON or Markdown) and want it carried out under
  verification, checkpointing, and recovery.
- You want each step independently DoD-verified (anti-self-grading) rather than trusted on the
  effector's say-so.
- You want a resumable/forkable run you can hand off between agents (Claude ↔ Codex) without
  losing committed work.

**Do not use it when:**
- You still need to design or change the plan — that is epiphany-plan / epiphany-spec. The executor
  **honors** a plan; it does not redesign one. A plan that declares itself not execution-ready makes
  the executor **HALT** (INV-17), it does not "fix" it.
- The plan author marked open blocking defects / a non-PASS gate — the executor stops and routes to
  a human (it will not override the plan author's readiness call).

---

## 3. How to run it

The artifact is driven by the harness. The canonical invocation:

```bash
# execute a real epiphany-plan execution plan (JSON):
goatcs-harness run <epiphany-executor>/graph.json --seed plan_path=<plan.json>
```

`read_plan` reads `plan_path` (`graph.json:40-48`, `modules/N-read_plan.md`); `ingest_plan`
normalizes Markdown to the JSON shape if needed (`plan.normalize_md`, a harness builtin tool —
`md_normalizer.py:4-12`), so you can also point `plan_path` at an epiphany-plan Markdown plan.

**Common flags / modes:**

```bash
# serial fallback — disable wave parallelism (every wave width 1; AX-01 / --serial):
... --serial

# heavy harness/forge steps: dispatch reasoning to Codex (claude-cli times out on large graphs):
... --provider codex

# resume / fork / handoff (REUSED harness substrate, INV-3 — not reimplemented):
goatcs-harness run --resume <session_dir>
goatcs-harness fork  <session_dir> --at-seq <n>
goatcs-harness handoff <session_dir> --from claude --to codex
```

Sandbox: runs under the harness `SandboxPolicy` (allowed fs roots + network gate). Tests drive the
real graph with `allowed_roots=[session, graph_dir], network=False`
(`tests/test_graph_drive.py:18-21`).

A `--serial` run is also the **bootstrap base case**: if the executor's own additive layer is broken,
the boring sequential applier (`baseline.py`) is the fallback (INV-14).

---

## 4. Concepts & architecture

### 4.1 The graph — 12 nodes, the driver pipeline + per-step loop

`graph.json` declares **12 nodes** and **13 edges** (`graph.json`):

```
read_plan → ingest_plan → honor_gates → build_context
            → schedule_steps → execute_step → precommit_gate → verify_dod
            → post_step_review → checkpoint_route → coverage_and_report
                                                    (+ human_gate, off precommit_gate)
```

The **per-step loop** is `schedule_steps → execute_step → precommit_gate → verify_dod →
post_step_review → checkpoint_route`, with the back-edge **`checkpoint_route → schedule_steps`**
(`E11`, `back-edge`, `retry_cap: 200` — `graph.json:620-627`). Routing is **machine-owned** (the
agent reasons at a node; the harness picks the next node from emitted signals):

| edge | from → to | gate condition |
|---|---|---|
| `E05` | schedule_steps → execute_step | `schedule_status == "ready"` |
| `E12` | schedule_steps → coverage_and_report | `schedule_status == "complete"` |
| `E07` | precommit_gate → verify_dod | `needs_human != true` |
| `E13` | precommit_gate → human_gate | `needs_human == true` |
| `E14` | human_gate → verify_dod | required |
| `E11` | checkpoint_route → schedule_steps | back-edge (loop), cap 200 |

`schedule_steps` re-derives readiness over the full plan each loop, so the run advances through all
N steps and exits via `complete` to `coverage_and_report` (terminal). A `blocked` status (steps
remain but none are ready) has **no out-edge** — the run halts for human resolution, the correct
fail-closed outcome (`modules/N-schedule_steps.md:57-62`). This was a regressed-then-fixed BLOCKER:
`tests/test_graph_drive.py` pins that the loop iterates every step then exits via coverage, and that
a `needs_human` step halts at the hitl `human_gate`.

**The 12 node bodies** (`modules/N-*.md`):

| node | tier | role |
|---|---|---|
| `read_plan` | no-llm (tool: `fs.read_text`) | byte-faithful read of the plan into `plan_raw` |
| `ingest_plan` | no-llm (tool: `plan.normalize_md`) | normalize + adapt → `normalized_plan` + `plan_metadata` |
| `honor_gates` | model-medium | INV-17 start gate: PROCEED or HALT on plan-declared gates/defects |
| `build_context` | model-medium | per-step look-behind/ahead, residency mode, thinking-tier, harness/forge context |
| `schedule_steps` | model-medium | dependency-aware ordering; emits `next_step` + `schedule_status` |
| `execute_step` | model-medium | classify → preview → gate irreversible → perform → record effects |
| `precommit_gate` | model-medium | irreversible-effect gate; sets `needs_human` |
| `verify_dod` | model-medium | independent DoD verdict (PASS/FAILED/BLOCKED) |
| `post_step_review` | model-medium | `state_delta` + append-only back-update + refreshed look-ahead |
| `checkpoint_route` | model-medium | append ledger, bind Burr checkpoint, advance lifecycle one stage, loop |
| `coverage_and_report` | model-medium | coverage closure + telemetry + resume brief + executed result |
| `human_gate` | no-llm, **hitl** | machine-enforced human stop; only a human writes `human_decision` via `override` |

### 4.2 The Python layer — module by module

The node bodies invoke this hand-authored, deterministic, unit-tested layer. Each module maps to a
spec phase (`S-Px-*`).

```
epiphany_executor/
├── __init__.py            # __version__ = "1.0.0"; package docstring (the COMPILE/REUSE charter)
├── contract_template.py   # S-P0: stamp_node_contract — one step → the 4-field-group node contract
├── census.py              # S-P1: INV-2 field census (every plan/step field → consumer or waiver, else BLOCK)
├── gate_defect.py         # S-P1: INV-17 start gate — evaluate_gate(plan) → HALT | PROCEED
├── md_normalizer.py       # S-P1: re-export of the harness plan.normalize_md (single source of truth)
├── scheduler.py           # S-P2: wave-parallel topological scheduler + static effect class + DAG
├── context_builder.py     # S-P2: per-step context, residency, thinking-tier, harness/forge pack + self-clobber
├── speculate.py           # S-P2: advisory speculative dry-run look-ahead (refines disjointness)
├── effector.py            # S-P3: wave effector fan-out + barrier (one worktree per cohort step)
├── dod.py                 # S-P3: two-class DoD verifier (objective/subjective, jury, anti-self-grading)
├── lifecycle.py           # S-P3: lifecycle state machine + ledger-fold recovery cursor (REUSES harness ledger/Burr)
├── recovery.py            # S-P3: INV-1 recovery menu + wave rollback (atomic-wave discard)
├── review.py              # S-P4: append-only back-update + forward-delta + background sentinel
├── effect_class.py        # S-P5: pre-execution per-command effect classification + v1 gate-only reliability
├── drift.py               # S-P5: plan-drift detection (canonicalized hash; reimport vs HALT)
├── coverage.py            # S-P5: requirement-coverage closure + F-10 waiver (executor- vs plan-caused orphan)
├── telemetry.py           # S-P5: health view + resume brief + halt-resolution surface
├── corpus.py              # S-P6: corpus enumeration + tuning/held-out partition
├── baseline.py            # S-P6: the boring sequential applier (benchmark comparator + INV-14 base case)
├── validate.py            # S-P6: corpus ingest+execute validation (BLOCKING gate)
├── benchmark.py           # S-P6: 3-arm superiority benchmark (decisive trio: back-update/recovery/coverage)
└── memory.py              # S-P8: cross-run Memory flywheel (versioned, revocable, advisory priors)

tools/
├── selfhost.py            # S-P8: dogfood — the executor runs its OWN build plan to CLEAN (INV-12)
├── v_battery.py           # S-P8: post-emit V-battery (BLOCKING re-verify gate, INV-9)
└── reconcile_forge.py     # non-clobber re-forge (additive copy; never overwrites hand-authored files)

docs/    bootstrap.py    graph.json    graph.schema.json    manifest.json    install.sh
```

One-line roles:

- **contract_template** — `stamp_node_contract(step)`; `assert_node_contract`; tolerant of both
  plan shapes; `LIFECYCLE_STATES`, `EFFECT_CLASSES`.
- **census** — `census(plans)` → `CensusReport`; `PLAN_LEVEL_CONSUMERS` / `STEP_LEVEL_CONSUMERS`
  are the single authority for "what reads what"; BLOCK on unconsumed field or stale binding.
- **gate_defect** — `evaluate_gate(plan)` → `GateDecision(decision=HALT|PROCEED, reasons, blocking_steps)`.
- **scheduler** — `schedule_waves`, `build_dag`, `topo_layers`, `partition_cohort`,
  `static_effect_class`, `FanoutBudget`, `Wave`; cycles (excluding back-edges) fail closed.
- **context_builder** — `build_step_context`, `resident_context_mode`, `allocate_thinking_tier`,
  `apply_memory_priors`, `harness_forge_pack`, `harness_forge_context_lines`, `detect_self_clobber`.
- **speculate** — `speculate_antichain`, `refine_cohort`; never commits a ledger entry.
- **effector** — `dispatch_wave`; staged (uncommitted) results at the barrier; one worktree per step.
- **dod** — `verify_dod`, `assemble_dod`, `classify_criterion`, `VerifierContext`, `conformance_check`.
- **lifecycle** — `LifecycleState`, `transition`, `LifecycleStore` (ledger fold), `make_burr_checkpoint`,
  `accepted_steps()` (steps that must not re-run on resume).
- **recovery** — `recovery_menu`, `on_verify_fail`, `wave_rollback`, `RecoveryOption`.
- **review** — `compute_state_delta`, `back_update`, `propagate_forward_delta`, `Sentinel`,
  `BackUpdateBudget`, `ConvergenceTracker`.
- **effect_class** — `classify_command`, `gating_decision`, `step_is_gated`; `auto_resume_irreversible`
  is INERT in v1 (raises until the S-P7 effect-ledger substrate exists).
- **drift** — `snapshot_hashes`, `check_drift` → `DriftResolution.{NONE,REIMPORT,HALT}`.
- **coverage** — `coverage_report`, `build_matrix`, `waive_plan_caused_orphan`.
- **telemetry** — `health_view`, `resume_brief`, `halt_resolution`, `resume_from_halt`, `HaltClass`.
- **corpus / baseline / validate / benchmark / memory** — the S-P6/S-P8 rigor + learning layer.

### 4.3 The harness substrate it REUSES (never reimplements, INV-3)

- `goatcs_harness.ledger.append/read` — the append-only audit ledger (lifecycle = fold over it).
- `goatcs_harness.persist.make_persister` — the Burr SQLite checkpoint (recovery cursor rides it).
- `goatcs_harness.fidelity` (`check_serializable`, `validate_submission` via `session.submit`) —
  the DoD verdict is recorded through the NAMED harness gate (`dod.py:167-178`), not a fork.
- `goatcs_harness.loader.load` / `build.build_application` / `run.run` — load + drive the graph
  (`bootstrap.py`, `tests/test_graph_drive.py`).
- resume / fork / handoff — harness CLI verbs; the executor adds no parallel state store.

---

## 5. Full reference

### 5.1 Per-step gates (in loop order)

1. **honor_gates — INV-17 start gate (once, before step 1).** `evaluate_gate(plan)` HALTs if
   `gate_status.verdict != PASS`, any open `blocking_defects`, any `structural_faults`, or any
   per-step `integration_checks.status` that is a BLOCKING DEFECT (`gate_defect.py:50-96`). A
   blocking-**type** gate that PASSED still PROCEEDs (BD-4 reconciliation — `gate_defect.py:69`,
   `modules/N-honor_gates.md:37-38`).
2. **execute_step — pre-execution effect classification.** Every command is classified before it
   runs (`effect_class.classify_command`, INV-15); unclassifiable ⇒ conservative
   `externally-irreversible`. An unclassified command halts.
3. **precommit_gate — irreversible-effect + human gate.** Requires a preceding checkpoint, an
   idempotency token, upstream verification, and PASS gate scope. Sets `needs_human = true` for §6
   markers (OQ-1, refusal trigger, plan-review gate S-G2, `human.final_gate` S-G14,
   §9-assumption-falsified), for a high-stakes irreversible effect, **or** when
   `step_context.self_clobber_paths` is non-empty (`modules/N-precommit_gate.md:39`).
4. **verify_dod — two-class DoD verifier.** DoD = `acceptance_criteria ∪ integration_checks ∪
   outputs`. Runs in a **fresh `VerifierContext`** that structurally cannot see the effector's
   reasoning (anti-self-grading; verifier ≠ effector — `dod.py:97-104`). Criteria split
   OBJECTIVE / SUBJECTIVE (ambiguous → stricter OBJECTIVE at low confidence); subjective never
   auto-passes; high-stakes escalates to an N-way **any-veto jury**. Empty acceptance+integration ⇒
   **BLOCKED** (INV-10). Verdict ∈ `PASS | FAILED | BLOCKED`.
5. **checkpoint_route — commit gate.** Appends the ledger entry, binds the Burr checkpoint, advances
   lifecycle exactly one monotone stage (`VERIFIED → ACCEPTED`). A non-PASS verdict appends nothing
   and leaves the step `IN_FLIGHT` → recovery (`modules/N-checkpoint_route.md:43`).

### 5.2 The census (INV-2)

`census(plans)` enumerates every plan-level and per-step key across a corpus and binds each to a
consumer via `PLAN_LEVEL_CONSUMERS` / `STEP_LEVEL_CONSUMERS` (`census.py:25-70`). Verdicts:
`CONSUMED`, `WAIVED` (explicit `metadata-only`), `SCHEMA-TOLERANT` (a `plan.schema.json` key the
emitter does not yet produce), `BLOCK-unconsumed` (a corpus key with no consumer — silent-drop
risk), `BLOCK-stale-binding` (a declared consumer for a key never seen). A new emitted field that
the map does not cover **BLOCKs** — that is the INV-2 enforcement.

Consumed plan-level keys include: `gate_status`, `blocking_defects`, `structural_faults`,
`build_order`, `steps`, `refinement_back_edges`, `source_spec`, `requirement_preservation`,
`schema_version`, and (harness/forge) `target_profile`, `harness_forge`. Consumed step-level keys
include: `step_id`, `goal`, `actions`, `inputs`, `outputs`, `dependencies`, `integration_checks`,
`acceptance_criteria`, `traces_to`/`traces_requirements`, `phase`, and (harness/forge)
`target_subsystem`, `obligation_class`.

### 5.3 Lifecycle states (`lifecycle.py:21-52`, `contract_template.py:29`)

`UNSTARTED → IN_FLIGHT → VERIFIED → ACCEPTED` (terminal success). Plus `BLOCKED` (precondition
unmet), `FAILED` (DoD failed → halt+recover), `AMENDED` (superseded by a ledgered plan-amendment),
`AWAITING` (background Task in flight). `LEGAL_TRANSITIONS` is enforced by `transition()`
(fail-closed `IllegalTransition`). An `ACCEPTED` step re-opens only via the explicit
`ACCEPTED → AMENDED → IN_FLIGHT` path (INV-7), never silently. Run-level aggregate `PARTIAL` is not a
per-step state. No ACCEPTED step re-runs on resume (INV-5, `accepted_steps()`).

### 5.4 Recovery options (`recovery.py:21-37`)

`recovery_menu` always offers `RETRY`, `FORK`, `HALT_FOR_HUMAN`; adds `ROLLBACK` only when the step
is **not** externally-irreversible (INV-7); adds `SKIP_WITH_WAIVER` only when downstream-safe. A
mid-wave failure discards **all** staged cohort worktrees (`wave_rollback`); the pre-wave checkpoint
is the recovery point (CV-01 atomic wave).

### 5.5 Plan fields consumed (authority: `census.py`)

See §5.2. The census is the single source of truth — any field listed there is bound to a behavior
or an explicit waiver; anything not listed BLOCKs by design.

---

## 6. Wave-parallel scheduler & AI-advantage modes

The scheduler computes **waves**: each wave is a parallel cohort + a serial residue
(`scheduler.py:53-67`). A step joins the parallel cohort **only if** it is provably
output-disjoint (canonicalized write-sets), statically non-irreversible (`local-mutating`), has
declared outputs, and shares no external resource — else it drops to the serial residue
(fail-closed; default serial unless independence is provable, `scheduler.py:9-21`). A step with no
declared outputs `conflicts_with_all` → forced serial (INV-16). The fan-out budget (`FanoutBudget`,
CV-03) caps concurrent effectors / jury width; overflow degrades to serial. `--serial` ⇒ every wave
width 1.

The machine-advantage levers (`SKILL.md:49-77`) are all **safety-bounded** and advisory: wave
fan-out (A.1), thinking-budget allocation (A.2, never down-tiers out of a gate), 1M context hold-all
(A.3), adversarial verification + jury (A.4), speculative dry-run (A.5, never commits), background
tasks (A.6), cross-run memory flywheel (A.7, raise-only), worktree isolation (A.8), background
ledger sentinel (A.9, append-only, 1-firing latch, quiesces mid-wave).

---

## 7. Examples

### 7.1 Run a clean plan to completion

```bash
goatcs-harness run /home/myuser/.claude/skills/epiphany-executor/graph.json \
  --seed plan_path=/path/to/my-execution-plan.json
```

`honor_gates` PROCEEDs (verdict PASS, no open defects); the loop runs each step through
execute → precommit → verify_dod → post_step_review → checkpoint, looping via `E11`; when every step
is ACCEPTED, `schedule_steps` emits `complete` and the run exits at `coverage_and_report` with a
coverage-closure report, telemetry health, a resume brief, and the executed result. The graph-drive
test pins exactly this: 4 steps → 5 schedule calls → final node `coverage_and_report`
(`tests/test_graph_drive.py:61-68`).

### 7.2 A HITL pause (irreversible / §6 / self-clobber)

```bash
goatcs-harness run <…>/graph.json --seed plan_path=<plan.json>
# … precommit_gate sets needs_human=true → run halts at human_gate (final_node=human_gate, verdict UNCERTAIN)

goatcs-harness override --session <dir> --node human_gate \
  --values '{"human_decision": "approve"}'
goatcs-harness run --resume <dir>
```

A HITL pause is **not a failure** — it is a machine-enforced stop awaiting a human decision
(`modules/N-human_gate.md`, `tests/test_graph_drive.py:71-79`). The agent does not self-resolve it.

---

## 8. Invariants

Grounded in the source (file:line in §11):

- **INV-2 — field census.** Every plan/step field is bound to a consumer or explicitly waived; an
  unbound field BLOCKs. (`census.py`)
- **INV-17 — start gate.** A plan that declares itself not execution-ready (non-PASS gate / open
  defect / structural fault / blocking IC) makes the executor HALT before step 1. (`gate_defect.py`)
- **INV-1 — fail-halt / never silently complete.** A FAILED DoD halts + checkpoints + offers
  recovery; the step is never marked ACCEPTED. (`recovery.py`, `HaltState.__post_init__`)
- **INV-10 — empty-acceptance BLOCKED.** A step with empty acceptance+integration is unverifiable →
  BLOCKED, never auto-passed. (`dod.py:147-148`, `contract_template.py:123-124`)
- **Anti-self-grading (AX-04).** The verifier runs in a fresh context with no field for the
  effector's reasoning; verifier ≠ effector; jury any-veto for high stakes. (`dod.py:97-104`)
- **INV-3 — reuse the substrate.** ledger/Burr/fidelity-gate/resume-fork-handoff are harness symbols,
  not reimplemented. (`lifecycle.py`, `dod.py:171`)
- **INV-5/6/7 — resume/append-only/bounded re-open.** No ACCEPTED step re-runs on resume; history is
  append-only; back-updates are bounded and terminate; irreversible undo is forbidden.
  (`lifecycle.py`, `review.py`)
- **INV-15/16/18 — pre-exec effect class / outputs lower-bound / shape tolerance.**
  (`effect_class.py`, `scheduler.py`, `contract_template.py`)

---

## 9. Failure modes & recovery

| trigger | outcome |
|---|---|
| Unconsumed plan field (no census consumer) | census **BLOCK-unconsumed** (or BLOCK-stale-binding for a declared-but-absent key) |
| Plan declares non-PASS gate / open defect | `honor_gates` **HALT** before any step (INV-17) |
| Empty `acceptance_criteria` (and no integration_checks) | `verify_dod` **BLOCKED**, never auto-passed (INV-10) |
| DoD FAILED | halt + checkpoint + recovery menu; step stays `IN_FLIGHT`/`FAILED`, never ACCEPTED (INV-1) |
| Externally-irreversible effect w/o idempotency token | **GATED** → human confirm, no auto-resume (INV-13, v1 gate-only) |
| §6 marker / high-stakes effect | `needs_human=true` → halt at `human_gate` (resolved by `override`) |
| Self-modifying plan output hits a LIVE skill/harness/forge dir | self-clobber guard → `needs_human` (redirect to an out-dir or human-confirm) |
| Mid-wave failure | discard all staged cohort worktrees; pre-wave checkpoint stands (CV-01) |
| Plan drift on a started step | drift **HALT** + human reconciliation; drift on UNSTARTED → safe reimport (`drift.py`) |
| Cycle in the forward DAG | `SchedulerError` (fail-closed) / `schedule_steps` surfaces members + HALT |
| Back-update budget exhausted | `BackUpdateExhausted` → halt + human gate (INV-7) |

Recovery is driven through the telemetry halt-resolution surface (`telemetry.py:96-148`): each halt
class (`DEFECT_ACK`, `DRIFT`, `IRREVERSIBLE_CONFIRM`, `WAIVER_ACK`, `BACKUPDATE_BUDGET`) has a
structured prompt + legal choices; `resume_from_halt` consumes a recorded decision and emits the
`run --resume` entry point.

---

## 10. Integration

### 10.1 Final stage of the pipeline

`epiphany-spec → epiphany-plan → epiphany-executor`. The executor consumes the plan epiphany-plan
emits; cross-link:
- **epiphany-plan** (`~/projects/epiphany-plan`, skill `epiphany-plan`) — emits the execution plan
  (Markdown default + `--json`).
- **goatcs-harness** (`~/projects/goatcs-harness`) — the runtime substrate (ledger / Burr / fidelity
  gate / run / fork / handoff). The S-P1 importer + `Node.step_contract` and the S-P7 effect-ledger
  co-deliverables live upstream there (`docs/BUILD-COMPLETE.md:31-36`).

### 10.2 harness/forge accommodation (additive, default-off)

Governed by the pipeline contract `~/docs/epiphany/harness-forge-pipeline-integration.md`. When a
plan declares `plan_meta.target_profile == "harness-forge"` (i.e. the artifact being built is itself
a harness skill, possibly forge-emitted):

- `ingest_plan` propagates `target_profile` + the `harness_forge` pack into `plan_metadata`
  (`modules/N-ingest_plan.md:39`).
- `census.py` has consumer entries for `target_profile` / `harness_forge` / `target_subsystem` /
  `obligation_class`, so a tagged plan does **not** trip the INV-2 unconsumed-field BLOCK (this
  closed a latent gap — `harness-forge-pipeline-integration.md:110-112`).
- `context_builder.harness_forge_pack` / `harness_forge_context_lines` inject provider-hint
  (`--provider codex` for heavy runs), harness-first ordering, in-scope primitives, and the
  exit-7 (static gate) / exit-11 (inline pause) conventions; `detect_self_clobber` + the AX DEEP-tier
  raise apply (`context_builder.py:93-135, 222-237`).
- **The self-clobber guard** (`precommit_gate`): when the pack is `self_modifying` and a step's
  `outputs[]` resolve into a LIVE install dir (`~/.claude/skills`, `~/projects/goatcs-harness`,
  `~/projects/epiphany-*`) without an explicit safe `out_dir`, the gate sets `needs_human` — the
  running executor/harness/forge could be overwritten mid-run. Path-**prefix** matching (a `/tmp/out/…`
  path that merely contains a live token is NOT flagged) with an `out_dir` exemption. This
  generalizes `tools/selfhost.py`'s bespoke per-step-id dry-run to any plan.

For a `generic` plan, all of the above is byte-identical to no-op (back-compat pinned by
`tests/test_harness_forge_integration.py` + `tests/test_pipeline_trace.py`).

### 10.3 Dogfooding (INV-12)

`tools/selfhost.py` runs the executor over **its own build plan** to a CLEAN terminal against a
sandbox (S-P0 forge / S-P7 promote steps dry-run, no self-clobber) and asserts the INV-12 tracker
(`docs/INV-12-cotuning-tracker.md`) has no silently-bypassed entries. The build reports 26 steps /
23 waves / 26 accepted, terminal CLEAN (`docs/BUILD-COMPLETE.md:18-24`).

---

## 11. Verification appendix (claims → file:line)

| claim | evidence |
|---|---|
| version `1.0.0` | `epiphany_executor/__init__.py:10`; `pyproject.toml:8`; `graph.json:6`; `manifest.json:3` |
| 12 nodes, 13 edges | `graph.json` (nodes block `:7-527`; edges `:528-649`) |
| per-step loop back-edge E11 cap 200 | `graph.json:620-627` |
| routing conditions E05/E07/E12/E13 | `graph.json:607-641` |
| COMPILE model = one step → node → action → checkpoint | `SKILL.md:36-47`; `contract_template.py:1-6` |
| 4 contract field-groups | `contract_template.py:36`, `:107-133`; `docs/contract-template.md` |
| shape tolerance INV-18 | `contract_template.py:16-23, 45-76` |
| INV-2 census + verdicts + consumers | `census.py:25-70, 129-171` |
| INV-17 start gate | `gate_defect.py:50-96` |
| BD-4 blocking-type-gate-on-PASS PROCEEDs | `gate_defect.py:69`; `modules/N-honor_gates.md:37-38` |
| two-class DoD + anti-self-grading + jury + INV-10 BLOCKED | `dod.py:97-104, 140-164` |
| DoD recorded through named harness fidelity gate | `dod.py:167-178` |
| lifecycle states + legal transitions | `lifecycle.py:21-52`; `contract_template.py:29-32` |
| ledger-fold recovery, no ACCEPTED re-run (INV-5) | `lifecycle.py:99-129` |
| recovery menu + wave rollback (CV-01) | `recovery.py:29-37, 79-92` |
| append-only back-update + sentinel (INV-6/7, CV-04) | `review.py:85-180` |
| pre-exec effect class + v1 gate-only (INV-13/15) | `effect_class.py:36-97` |
| wave scheduler safety + INV-16 + --serial | `scheduler.py:9-21, 201-245` |
| drift HALT vs reimport | `drift.py:63-84` |
| coverage closure + F-10 waiver | `coverage.py:84-116` |
| harness/forge pack + self-clobber guard | `context_builder.py:93-135, 222-250`; `modules/N-precommit_gate.md:39`; `~/docs/epiphany/harness-forge-pipeline-integration.md:109-120` |
| census consumers for harness/forge tags | `census.py:42-46, 66-69`; `tests/test_harness_forge_integration.py:56-79` |
| selfhost dogfood CLEAN + INV-12 | `tools/selfhost.py`; `docs/BUILD-COMPLETE.md:18-24` |
| graph actually drives (loop + human_gate) | `tests/test_graph_drive.py` |
| forge provenance (power profile, best-of-3) | `provenance.json`; `RATIONALE.md`; `SKILL.md:91-93` |
| test suite | **152 passed** (`pytest -q`, 22 test files) |

---

*Forge provenance: authored by `goatcs-harness forge --profile power` (GoT-basic, best-of-3);
topology corrected + contracts hand-authored. Regenerable via the non-clobber re-forge path
(`tools/reconcile_forge.py`).*
