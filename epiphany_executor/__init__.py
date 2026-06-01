"""epiphany-executor — a forge-emitted goatcs-harness skill that executes an epiphany-plan
step by step (COMPILE model: one plan step -> one harness node -> one checkpoint).

This package is the hand-authored layer ABOVE the goatcs-harness reversibility boundary
(plan importer, contract templates, scheduler, DoD verifier, lifecycle, post-step review,
effect classification, drift/coverage/telemetry). It REUSES the harness substrate
(ledger, Burr checkpoint, fidelity gate, resume/fork/handoff) and never reimplements it.
"""

__version__ = "1.0.0"
