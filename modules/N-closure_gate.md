---
node_id: closure_gate
exec_type: inline
tier: no-llm
input_ports:
  - { port: plan, signal_field: normalized_plan, required: false }
  - { port: skill_pkg, signal_field: skill_pkg, required: false }
output_ports:
  - { port: closure_check, signal_field: closure_check, required: true }
  - { port: verdict, signal_field: verdict, required: true }
  - { port: gaps, signal_field: closure_gaps, required: false }
---

# closure_gate — deterministic anti-false-green gate (NO-LLM)

This node is **mechanical** (`tier: no-llm`, `tool: wiring.closure_gate`). The harness driver runs
it; the inline agent never reasons or submits it, so it **cannot be skipped or faked**. It runs the
`goatcs-harness wiring-check` STATIC battery (C1 reachability / C2 mechanism-match / C4 ledger /
C5 identity / C7 orphan-module) in-process over the built `skill_pkg`, against the plan's authored
`wiring_contract` (or a bootstrapped one). It is N/A (`pass`) for a non-harness-skill plan or when no
`skill_pkg` is resolvable (from a seed signal or `plan_meta.skill_pkg`).

Routing: `closure_check == "pass"` → `EXT_done` (clean terminal); `closure_check == "blocked"` →
`EXT_closure_blocked` (the node writes `verdict = FAIL`, so the run reports FAILED, not PASS, while a
declared capability is unwired — the gap-list is in `closure_gaps`). Born from the epiphany-report-v3
false-green: capability **present** ≠ capability **wired**.

**`skill_pkg` precedence:** the AUTHORED `plan_meta.skill_pkg` wins over the seed/signal, so an
agent-writable signal cannot redirect the gate to a known-green skill (un-fakeability).

**Harness-ledger facet tie + waiver surfacing (S8 / WC-10/11 / INV-6).** For a harness plan carrying
a `harness_ledger`, the closure report (persisted to `closure.json` by `bootstrap.close_session` via
`closure_gate.facet_closure_report`) MUST list **every** facet as `satisfied` / `waived` / `missing`.
A `full`/`thin`-claimed facet that the built `skill_pkg` never references is `missing` → it BLOCKS the
close (kill-criterion (c): a present-but-empty facet reaching the executor is never a silent pass). A
`waived` facet is surfaced explicitly **with its recorded reason** — an audited, downstream-visible
event, never a silent hole. A generic plan (no `harness_ledger`) yields `applicable:false` and no
route change (INV-1 byte-identity).

**Residual (by design):** this in-graph gate is STATIC-ONLY. It catches the primary false-green modes
— an orphan/unreachable module (C1/C7), an unbound `tool_call` (C2, the erv3 `measured.run` case), a
stale identity (C5), a lying ledger claim (C4). It does NOT run the `$0` C3 smoke (which would execute
the skill's graph), so the rarer **statically-bound-but-never-fires** case is not caught HERE; that is
covered by the `wiring-check` CLI and the `coverage_and_report` §5 module-mandate which run the fuller
check (incl. C3) at ship boundaries. The in-graph node is the un-skippable STATIC floor; smoke is the
best-effort behavioral layer on top.
