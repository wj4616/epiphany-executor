# INV-12 Co-Tuning Tracker (append-only)

Every goatcs-harness / goatcs-forge limitation hit while **building or running**
epiphany-executor is captured here, triaged, fixed **upstream** (never patched locally in the
skill), and re-verified on the shared corpus. A build step is NOT ACCEPTED while it has an
open entry it silently bypassed (spec §17, INV-12).

Entry schema: `{id, interaction-point (DF-n), gap, system (harness|forge|executor|upstream-skill), fix, re-verify, status}`

## Seed entries (from spec §17)

| id | DF | gap | system | fix | re-verify | status |
|----|----|-----|--------|-----|-----------|--------|
| a | DF-2 | epiphany-plan-JSON importer dialect missing | goatcs-harness | add `epiphany-plan` importer | load+smoke each ref plan | OPEN (S-P1) |
| b | — | MD→schema normalizers | executor (additive) | normalizers in skill | corpus ingest | OPEN (S-P1) |
| c | DF-1 | forge/profile gaps at --profile power | goatcs-forge | fix upstream | post-emit V-battery | OPEN (S-P0) |
| d | DF-3 | effect-ledger/idempotency substrate primitive | goatcs-harness | add substrate | resume double-fire test | OPEN (S-P7) |
| e | DF-4 | checkpoint/resume edge cases | goatcs-harness persist | fix upstream | kill+resume recovery test | OPEN (S-P7) |
| f | DF-5 | subjective-criteria classifier hooks | goatcs-harness verify | add hooks | classifier conformance | OPEN (S-P3) |
| g | DF-6 | shared reference-plan regression suite | all three | shared suite | superiority benchmark | OPEN (S-P6) |
| h | DF-7 | epiphany-plan emitter ↔ plan.schema.json reconciliation | epiphany-plan | emit typed deps/edge_class/traces_requirements/per-step back-edges OR update schema | re-verify on shared corpus | OPEN (S-P7-handoff; build does NOT block) |

## Build-discovered entries

_(append below as gaps are hit during S-P0…S-P8)_

| id | DF | gap | system | fix | re-verify | status |
|----|----|-----|--------|-----|-----------|--------|
| BD-1 | DF-1 | First S-P0 forge (`--profile power`) abstained: intent-alignment "missing required coverage: ['scheduling']" — all 3 candidates failed identically (systematic). Diagnosed via `--best-of-n 1` which surfaced the real reason (the tournament path swallows per-candidate reasons as "all candidates failed"). | forge (friction, NOT defect) | Per STATE.md this is irreducible LLM judge-vs-designer coverage friction — the intent gate is correctly abstaining. Resolved by strengthening the brief so "scheduling" is an unmistakable, clearly-covered responsibility (input fix, not a forge patch). | re-forge passes intent gate | RESOLVED-BY-BRIEF (forge behaving correctly) |
| BD-2 | DF-1 | UX gap (minor): `_best_of_n` (forge.py:467-470) discards per-candidate `res.reasons`, returning only "best-of-N: all candidates failed" — opaque for diagnosis. `--best-of-n 1` is the workaround. | goatcs-forge | OPTIONAL upstream: surface the most-common candidate-failure reason in the aggregate message. Low priority (workaround exists). | n/a | OPEN-MINOR (deferred; non-blocking) |
