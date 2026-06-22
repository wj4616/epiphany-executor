---
node_id: human_gate
exec_type: inline
tier: no-llm
hitl: true
hitl_editable_signals:
  - human_decision
input_ports:
  - port: precommit_approval
    format: any
    signal_field: precommit_approval
    required: true
  - port: needs_human
    format: any
    signal_field: needs_human
    required: true
output_ports:
  - port: human_decision
    format: any
    signal_field: human_decision
    required: true
---

# human_gate — HUMAN DECISION GATE (§6)

This node is a **machine-enforced human stop**. The run reaches it only when `precommit_gate`
flagged `needs_human == true` — i.e. the current step carries a §6 marker: **OQ-1** (vrr-catalog
re-validation before R1 closes), the **refusal trigger** (an unfunded but needed primitive), a
**plan-review gate (S-G2)**, the **`human.final_gate` (S-G14)** for a high-stakes claim, or a
**§9-assumption-falsified** halt.

Under `--provider inline` the driving agent is the reasoner — but a §6 stop is a decision the agent
**must not** self-resolve. So this node is `hitl: true`: the harness halts with `awaiting_human`,
and a **human** advances it with:

```
goatcs-harness override --session <dir> --node human_gate --values '{"human_decision": "<approve|reject|amend …>"}'
```

then resumes. The agent does NOT submit this node. Present `precommit_approval` + the step's §6
context to the human; do not fabricate `human_decision`. On `reject`/`amend`, the human's decision
is an authoritative spec/plan amendment that downstream nodes must honor.

`human_decision` is the only field written, and only by the human via `override`.
