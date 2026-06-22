# INV-12 Co-Tuning Tracker (append-only)

Every goatcs-harness / goatcs-forge limitation hit while **building or running**
epiphany-executor is captured here, triaged, fixed **upstream** (never patched locally in the
skill), and re-verified on the shared corpus. A build step is NOT ACCEPTED while it has an
open entry it silently bypassed (spec §17, INV-12).

Entry schema: `{id, interaction-point (DF-n), gap, system (harness|forge|executor|upstream-skill), fix, re-verify, status}`

## Seed entries (from spec §17)

| id | DF | gap | system | fix | re-verify | status |
|----|----|-----|--------|-----|-----------|--------|
| a | DF-2 | epiphany-plan-JSON importer dialect missing | goatcs-harness | add `epiphany-plan` importer | load+smoke each ref plan | RESOLVED (S-P1; see BD-3) |
| b | — | MD→schema normalizers | executor (additive) | normalizers in skill | corpus ingest | RESOLVED (S-P1; see BD-5) |
| c | DF-1 | forge/profile gaps at --profile power | goatcs-forge | fix upstream | post-emit V-battery | OPEN (S-P0) |
| d | DF-3 | effect-ledger/idempotency substrate primitive | goatcs-harness | add substrate | resume double-fire test | RESOLVED (S-P7; `effect_ledger.py` commit-then-replay; BD-6) |
| e | DF-4 | checkpoint/resume edge cases | goatcs-harness persist | fix upstream | kill+resume recovery test | RESOLVED (S-P7; commit-then-replay closes the perform-vs-record window; BD-6) |
| f | DF-5 | subjective-criteria classifier hooks | goatcs-harness verify | add hooks | classifier conformance | ADDRESSED-EXECUTOR-SIDE (S-P3 `dod.py` two-class classifier + anti-self-grading; verdict via NAMED harness gate symbol. Execution-grounded verify IN the harness is the future round per STATE.md) |
| g | DF-6 | shared reference-plan regression suite | all three | shared suite | superiority benchmark | RESOLVED (S-P6; corpus+validate+benchmark; ALL_OK + ALL_PLANS_PASS_R018) |
| h | DF-7 | epiphany-plan emitter ↔ plan.schema.json reconciliation | epiphany-plan | emit typed deps/edge_class/traces_requirements/per-step back-edges OR update schema | re-verify on shared corpus | HANDOFF-OPENED (S-P7-handoff; `docs/handoff-epiphany-plan-reconciliation.md`; build does NOT block, INV-18) |

## Build-discovered entries

_(append below as gaps are hit during S-P0…S-P8)_

| id | DF | gap | system | fix | re-verify | status |
|----|----|-----|--------|-----|-----------|--------|
| BD-1 | DF-1 | First S-P0 forge (`--profile power`) abstained: intent-alignment "missing required coverage: ['scheduling']" — all 3 candidates failed identically (systematic). Diagnosed via `--best-of-n 1` which surfaced the real reason (the tournament path swallows per-candidate reasons as "all candidates failed"). | forge (friction, NOT defect) | Per STATE.md this is irreducible LLM judge-vs-designer coverage friction — the intent gate is correctly abstaining. Resolved by strengthening the brief so "scheduling" is an unmistakable, clearly-covered responsibility (input fix, not a forge patch). | re-forge passes intent gate | RESOLVED-BY-BRIEF (forge behaving correctly) |
| BD-2 | DF-1 | UX gap (minor): `_best_of_n` (forge.py:467-470) discards per-candidate `res.reasons`, returning only "best-of-N: all candidates failed" — opaque for diagnosis. `--best-of-n 1` is the workaround. | goatcs-forge | OPTIONAL upstream: surface the most-common candidate-failure reason in the aggregate message. Low priority (workaround exists). | n/a | OPEN-MINOR (deferred; non-blocking) |
| BD-3 | DF-2 | epiphany-plan-JSON importer was MISSING from the harness (seed item `a`). | goatcs-harness | DONE: added `goatcs_harness/epiphany_plan_importer.py` + `detect_dialect` triad route + `loader.load()` dispatch (additive, INV-14-clean; commit 4bb3f4d). | 20 importer tests + all 3 real runs (82/37/66) load + full harness suite green (1566 passed/22 skipped) | RESOLVED (S-P1-importer) |
| BD-4 | DF-7 | The 3 REAL emitted runs carry **NO `schema_version`/`$schema`/dialect discriminator** and `build_order` is **prose layer-label strings** (step_ids embedded, arrow/comma-separated), NOT step-id arrays — diverges from plan.schema.json. Concrete instance of the schema↔emitter gap (seed item `h`). | epiphany-plan (emitter) | TOLERATED upstream-of-fix: importer discriminates on the `build_order`+`steps`+`gate_status` triad (no version field needed) and parses step_ids out of the prose layers; ordering authority is per-step `dependencies`, build_order used only for coarse inter-layer sequence. Standing co-tuning ask: emit a `schema_version` + structured `build_order` (step-id arrays) OR update plan.schema.json to the real shape. | re-verify on shared corpus when reconciled (S-P7-handoff gate) | HANDOFF-OPENED (build does NOT block, INV-18; see `docs/handoff-epiphany-plan-reconciliation.md`) |
| BD-6 | DF-3/4 | Harness lacked an effect-ledger / idempotency substrate (commit-then-replay) + worktree-isolation + Workflow-compilation primitives that the executor's AX-06/08 + v2 irreversible auto-resume (INV-13) need. | goatcs-harness | DONE (S-P7-substrate, pinned branch, additive/INV-DET): `effect_ledger.py` (commit-then-replay, EffectClass taxonomy, DoubleApply guard), `worktree.py` (create/merge/discard + ledger events), `workflow_compile.py` (deterministic topo compile). | 9 harness substrate tests + CV-07 reproduces --serial + full harness suite green | RESOLVED (S-P7-substrate) |

### Convergence audit round (2026-06-01 — post-build, "audit & fix to convergence")

| id | DF | gap | system | fix | re-verify | status |
|----|----|-----|--------|-----|-----------|--------|
| BD-7 | DF-1 | `_best_of_n` discarded per-candidate reasons → opaque "best-of-N: all candidates failed" (BD-2 escalated). | goatcs-forge | DONE: aggregate + surface a representative per-candidate failure summary (forge.py). | `tests/test_forge_audit_fixes.py` + harness suite 1581 green | RESOLVED |
| BD-8 | DF-1 | Emitted `skill_name` defaulted to generic `forged-skill`; no CLI name; install.sh/SKILL.md placeholders. | goatcs-forge | DONE: `forge --name` flag + `_infer_skill_name(brief)`; the executor brief now infers `epiphany-executor`. | name-inference tests + harness suite green | RESOLVED |
| BD-9 | DF-7 | Live designer emits unreconverged `required` fan-outs / L2-failing topologies for complex tier-3 briefs → forge UNCERTAIN (both S-P0 forge runs). | goatcs-forge (designer quality) | NOT-A-BUG: forge correctly ABSTAINS (gate working; auto-rewriting a true fan-out is unsafe). `repair_topology` handles cycle-fanouts (regression-locked). Logged in harness STATE.md as v2.1 designer-quality evidence. | repair regression test + STATE.md | DOCUMENTED (open v2.1 opportunity) |
| BD-10 | DF-2 | Harness `stamp_step_contract` duplicates the skill's `stamp_node_contract` → drift hazard. | harness + executor | DONE: cross-repo conformance test pins agreement (executor `tests/test_audit_convergence.py`). | conformance test (synthetic + real-run steps) | RESOLVED (drift pinned) |
| BD-11 | — | `reconcile_forge.py` added an orphan re-forge module (`N-recovery.md`) not referenced by the preserved graph. | executor (additive) | DONE: reconcile skips staging `modules/` files not referenced by the live graph.json; reports `skipped_orphans`. | EX-1 tests | RESOLVED |
| BD-12 | DF-1 | Forge emits dead signals (outputs produced but never read/carried — 6 in the executor graph). | goatcs-forge | OPEN-LOW: a post-emit prune/warn pass would tighten graph quality. Advisory only (non-blocking). | n/a | OPEN-LOW (deferred) |
| BD-5 | DF-2 | MD reference plans render typed deps as ``` `S-id` — kind: data · edge_class: ... ``` prose bullets; brainstorming MD has no per-step fields. | executor (additive, item `b`) | DONE: `epiphany_executor/md_normalizer.py` extracts the bare step_id + preserves edge_class as a typed dep; brainstorming path emits empty fields + `lossy_fields[]` + BLOCKING gate (degraded ≠ authoritative). | 6 ref MD plans normalize+import zero-lossy; brainstorming lossy+gated | RESOLVED (S-P1-importer executor side) |
