"""End-to-end GRAPH drive (the artifact `goatcs-harness run graph.json` actually executes).

Prior validation drove the standalone Python modules (selfhost.py); the graph was never driven.
These tests drive the real graph.json with a scripted invoke seam (deterministic, offline) and
assert the post-audit fixes hold: the work-queue loop iterates EVERY step then exits via
coverage_and_report (BLOCKER-1), and a §6 step halts at the hitl human_gate (BLOCKER-2).
"""
import json
import os

from goatcs_harness.run import run
from goatcs_harness.sandbox import SandboxPolicy

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = os.path.join(HERE, "graph.json")


def _sandbox(tmp_path):
    # grant fs-read of the plan + session, and the graph dir (SAF-07 gating)
    return SandboxPolicy(allowed_roots=[str(tmp_path), HERE], network=False)


def _plan(tmp_path, n):
    body = "# Test Plan\n\n"
    for i in range(1, n + 1):
        dep = f"- **dependencies:** S{i-1}\n" if i > 1 else ""
        body += f"### S{i}\n- **goal:** step {i}\n{dep}\n"
    body += ("## Coverage Verdict\n- **decision:** PASS\n- **blocking:** true\n\n"
             "## Execution Order\n" + " -> ".join(f"S{i}" for i in range(1, n + 1)) + "\n")
    p = tmp_path / "plan.md"
    p.write_text(body)
    return str(p)


def _scripted(n_steps, needs_human=False):
    """Stateful seam: schedule_steps emits `ready` for n_steps calls then `complete`."""
    st = {"sched": 0}
    fixed = {
        "honor_gates": {"gate_decision": {"verdict": "PROCEED"}},
        "build_context": {"step_context": {}, "look_ahead": {}},
        "execute_step": {"step_effects": {}, "effect_records": []},
        "precommit_gate": {"precommit_approval": {"approved": True}, "needs_human": needs_human},
        "verify_dod": {"dod_verdict": {"verdict": "PASS"}},
        "post_step_review": {"state_delta": {}, "look_ahead": {}},
        "checkpoint_route": {"ledger_state": {}, "lifecycle_status": "ACCEPTED"},
        "coverage_and_report": {"coverage_closure": {}, "telemetry_health": {},
                                "resume_brief": {}, "executed_result": {}},
    }

    def inv(prompt, *, cast=None, node="", attempt=0):
        if node == "schedule_steps":
            st["sched"] += 1
            if st["sched"] <= n_steps:
                return json.dumps({"schedule": [f"S{i}" for i in range(st["sched"], n_steps + 1)],
                                   "next_step": f"S{st['sched']}", "schedule_status": "ready"})
            return json.dumps({"schedule": [], "next_step": "", "schedule_status": "complete"})
        return json.dumps(fixed.get(node, {}))
    return inv, st


def test_graph_drives_all_steps_then_exits(tmp_path):
    # BLOCKER-1 regression: the loop must iterate every step (not 2/48) and exit via coverage.
    plan = _plan(tmp_path, 4)
    inv, st = _scripted(4)
    res = run(GRAPH, seed={"plan_path": plan}, _invoke=inv,
              session_dir=str(tmp_path / "s"), provider="codex", sandbox=_sandbox(tmp_path))
    assert res.final_node == "coverage_and_report"          # clean terminal, not a 2-step stop
    assert st["sched"] == 5                                  # 4 ready + 1 complete = looped per step


def test_step6_marker_halts_at_human_gate(tmp_path):
    # BLOCKER-2 regression: a step flagged needs_human halts at the hitl human_gate (not self-resolved).
    plan = _plan(tmp_path, 1)
    inv, _ = _scripted(1, needs_human=True)
    res = run(GRAPH, seed={"plan_path": plan}, _invoke=inv,
              session_dir=str(tmp_path / "s"), provider="codex", sandbox=_sandbox(tmp_path))
    assert res.final_node == "human_gate"                    # stopped at the human gate
    from goatcs_harness.generator.verdict import Verdict
    assert res.verdict is Verdict.UNCERTAIN                  # not a PASS; awaits human override
