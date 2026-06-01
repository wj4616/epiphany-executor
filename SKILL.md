# forged-skill

## NAME

`forged-skill` — a native graph-of-agentic-thought skill ((derived at runtime)).

## INVOCATION

Run via the harness:
```
goatcs-harness run graph.json
```
Provider-agnostic: the graph is identical across runtimes; only the live author/runtime provider differs (see RUNTIME CONVENTIONS).

## RUNTIME CONVENTIONS

This skill is **provider-agnostic** — one graph, any supported runtime. Runtime preflight — it runs under:
- `claude-cli`
- `codex`

The harness selects/falls back across these at run time; no per-agent variant is emitted (v2.0).

## ALGORITHM

Topology class: **(derived at runtime)**. The graph has 11 node(s) and 13 edge(s); execution follows the declared edges from the entrypoint to a clean sink. Each node reads its declared input ports and writes exactly its declared output ports.

## NODE REGISTRY

| node | type | output ports |
|---|---|---|
| `read_plan` | inline | plan_raw |
| `ingest_plan` | inline | normalized_plan, plan_metadata |
| `honor_gates` | inline | gate_decision |
| `build_context` | inline | step_context, look_ahead |
| `schedule_steps` | inline | schedule, next_step |
| `execute_step` | inline | step_effects, effect_records |
| `precommit_gate` | inline | precommit_approval |
| `verify_dod` | inline | dod_verdict |
| `post_step_review` | inline | state_delta, look_ahead |
| `checkpoint_route` | inline | ledger_state, lifecycle_status |
| `coverage_and_report` | inline | coverage_closure, telemetry_health, resume_brief, executed_result |

## EDGE CASES

- A missing required input is signaled, never invented.
- A node that cannot satisfy its contract abstains rather than emitting a placeholder.
- Out-of-envelope / contradictory input → the skill halts with a reason.

## DESIGN NOTES

Authored by forge from a brief. Topology `(derived at runtime)` chosen for the task's structure; the advantage floor for the class is enforced at design time.
