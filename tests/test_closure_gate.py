"""WP6 (isolated executor): closure-gate gates coverage->done; closure-blocked on red."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from epiphany_executor import closure_gate as CGATE

GOATCS = "/home/myuser/projects/goatcs-harness"
WIRED_SKILL = os.path.join(GOATCS, "tests", "fixtures", "wired_skill")
WIRED_CONTRACT_ROW = {
    "id": "CAP-echo", "requirement": "echo fires", "mechanism": "tool_call",
    "sites": [{"tool": "data.passthrough", "node": "echo_node"}],
    "fired_marker": [{"kind": "ledger_tool", "value": "data.passthrough"}],
    "smoke_input": '{"value": "hi"}'}

ERV3_SKILL = "/home/myuser/docs/solution/2026-06-07-epiphany-report-v3/skill"
ERV3_PLAN = "/home/myuser/docs/solution/2026-06-07-epiphany-report-v3/plan.json"


def test_non_harness_plan_is_na_done():
    plan = {"plan_meta": {"target_profile": "web-app"}, "steps": [{"step_id": "X"}]}
    d = CGATE.enforce_closure(plan, WIRED_SKILL)
    assert d["route"] == "done" and d["gate"]["applicable"] is False


def test_green_authored_contract_reaches_done():
    plan = {"plan_meta": {"target_profile": "harness-skill"},
            "wiring_contract": [WIRED_CONTRACT_ROW], "steps": []}
    d = CGATE.enforce_closure(plan, WIRED_SKILL)
    assert d["route"] == "done"
    assert d["gate"]["exit_code"] == 0


def test_red_contract_drives_closure_blocked_with_gaps():
    # an authored contract that is RED on the wired skill (names a tool that isn't bound)
    red_row = dict(WIRED_CONTRACT_ROW, id="CAP-unbound",
                   sites=[{"tool": "measured.run"}],
                   fired_marker=[{"kind": "ledger_tool", "value": "measured.run"}])
    plan = {"plan_meta": {"target_profile": "harness-skill"},
            "wiring_contract": [red_row], "steps": []}
    d = CGATE.enforce_closure(plan, WIRED_SKILL)
    assert d["route"] == CGATE.CLOSURE_BLOCKED
    assert d["halt_state"] == "closure-blocked"
    assert any("measured.run" in g for g in d["gaps"])


@pytest.mark.skipif(not os.path.exists(ERV3_SKILL), reason="erv3 absent")
def test_erv3_bootstrapped_fallback_closure_blocked():
    # no authored wiring_contract -> bootstrapped from plan_path (never vacuous) -> RED
    plan = json.load(open(ERV3_PLAN))
    assert "wiring_contract" not in plan
    d = CGATE.enforce_closure(plan, ERV3_SKILL, plan_path=ERV3_PLAN)
    assert d["route"] == CGATE.CLOSURE_BLOCKED
    assert len(d["gaps"]) > 0
    # the gap-list names the orphan helpers + unbound tools
    blob = " ".join(d["gaps"])
    assert "streams" in blob and "measured.run" in blob


def test_coverage_closure_with_gate_blocks_done_on_red():
    red_row = dict(WIRED_CONTRACT_ROW, id="CAP-x", sites=[{"tool": "nope.tool"}],
                   fired_marker=[{"kind": "ledger_tool", "value": "nope.tool"}])
    plan = {"plan_meta": {"target_profile": "harness-skill"},
            "wiring_contract": [red_row], "steps": []}
    out = CGATE.coverage_closure_with_gate(plan, WIRED_SKILL, {"requirements": "all covered"})
    assert out["closure_blocked"] is True and out["route"] == "closure-blocked"
    assert out["requirements"] == "all covered"   # base coverage preserved
