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
    # With the in-graph closure gate, a NON-harness plan drives coverage_and_report -> closure_gate
    # (N/A -> pass) -> EXT_done, so the last executed node is now closure_gate and the run is clean.
    plan = _plan(tmp_path, 4)
    inv, st = _scripted(4)
    res = run(GRAPH, seed={"plan_path": plan}, _invoke=inv,
              session_dir=str(tmp_path / "s"), provider="codex", sandbox=_sandbox(tmp_path))
    assert res.final_node == "closure_gate"                  # new clean terminal (gate then EXT_done)
    assert st["sched"] == 5                                  # 4 ready + 1 complete = looped per step
    assert str(res.verdict) in ("Verdict.PASS", "PASS")     # non-harness plan -> gate N/A -> PASS


def _harness_skill_plan(tmp_path, skill_pkg, contract_rows):
    """A 1-step harness-skill JSON plan carrying a wiring_contract + skill_pkg."""
    doc = {
        "plan_meta": {"plan_id": "p", "schema": "epiphany-plan/plan@1.1.0", "source_spec": "s.md",
                      "target_profile": "harness-forge", "skill_pkg": skill_pkg},
        "wiring_contract": contract_rows,
        "coverage_verdict": {"decision": "PASS", "blocking": True, "rationale": "ok"},
        "execution_order": ["S1"], "build_order": ["S1"],
        "steps": [{"step_id": "S1", "goal": "build the skill", "actions": ["a"],
                   "acceptance_criteria": ["ac"], "traces_requirements": ["R1"], "dependencies": []}],
    }
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(doc))
    return str(p)


def test_in_graph_gate_BLOCKS_red_harness_skill(tmp_path):
    """THE hardening: a harness-skill plan whose declared capabilities are UNWIRED drives the run
    deterministically (no-llm node, agent cannot skip) to EXT_closure_blocked with verdict=FAIL —
    a clean done is unreachable while a capability is unwired."""
    erv3 = "/home/myuser/docs/solution/2026-06-07-epiphany-report-v3/skill"
    if not os.path.exists(erv3):
        import pytest
        pytest.skip("erv3 skill absent")
    red_contract = [{"id": "TOOL-measured.run", "requirement": "measured verify wired",
                     "mechanism": "tool_call", "sites": [{"tool": "measured.run"}],
                     "fired_marker": [{"kind": "ledger_tool", "value": "measured.run"}], "smoke_input": "x"}]
    plan = _harness_skill_plan(tmp_path, erv3, red_contract)
    inv, st = _scripted(1)
    res = run(GRAPH, seed={"plan_path": plan, "skill_pkg": erv3}, _invoke=inv,
              session_dir=str(tmp_path / "s"), provider="codex",
              sandbox=SandboxPolicy(allowed_roots=[str(tmp_path), HERE, erv3], network=False))
    assert res.final_node == "closure_gate"
    assert str(res.verdict) in ("Verdict.FAIL", "FAIL")     # verdict DOWNGRADED by the gate
    assert res.state.get("closure_check") == "blocked"
    assert res.state.get("closure_gaps")                    # the exact gap-list is carried


def test_in_graph_gate_PASSES_green_harness_skill(tmp_path):
    """A WIRED harness-skill plan drives through the gate to EXT_done with PASS."""
    fixture = "/home/myuser/projects/goatcs-harness/tests/fixtures/wired_skill"
    if not os.path.exists(fixture):
        import pytest
        pytest.skip("wired fixture absent")
    # The wired_skill fixture's echo_node is a `data.passthrough` tool_call (impl=None) — so the
    # green capability is a TOOL_CALL that fires on the $0 smoke, NOT a node_body bound to a module.
    # (A node_body row would require a node `impl` binding to wired_skill.echo, which the fixture does
    # not declare — wiring-check correctly rejects that as cosmetic wiring. Fixed 2026-06-13.)
    green_contract = [{"id": "CAP-echo", "requirement": "echo fires", "mechanism": "tool_call",
                       "sites": [{"tool": "data.passthrough", "node": "echo_node"}],
                       "fired_marker": [{"kind": "ledger_tool", "value": "data.passthrough"}],
                       "smoke_input": "x"}]
    plan = _harness_skill_plan(tmp_path, fixture, green_contract)
    inv, st = _scripted(1)
    res = run(GRAPH, seed={"plan_path": plan, "skill_pkg": fixture}, _invoke=inv,
              session_dir=str(tmp_path / "s"), provider="codex",
              sandbox=SandboxPolicy(allowed_roots=[str(tmp_path), HERE, fixture], network=False))
    assert res.final_node == "closure_gate"
    assert res.state.get("closure_check") == "pass"
    assert str(res.verdict) in ("Verdict.PASS", "PASS")


def test_step6_marker_halts_at_human_gate(tmp_path):
    # BLOCKER-2 regression: a step flagged needs_human halts at the hitl human_gate (not self-resolved).
    plan = _plan(tmp_path, 1)
    inv, _ = _scripted(1, needs_human=True)
    res = run(GRAPH, seed={"plan_path": plan}, _invoke=inv,
              session_dir=str(tmp_path / "s"), provider="codex", sandbox=_sandbox(tmp_path))
    assert res.final_node == "human_gate"                    # stopped at the human gate
    from goatcs_harness.generator.verdict import Verdict
    assert res.verdict is Verdict.UNCERTAIN                  # not a PASS; awaits human override
