"""Inline operating-contract boundary hooks + closure-gate detection/discovery fixes (2026-06-13).

Regression cover for two real false-green/false-block bugs found auditing the executor's own
operation, plus the bootstrap scaffold that forces the REAL coverage/closure modules to run at the
inline-run boundaries.
"""
import json
import os

import bootstrap
from epiphany_executor import closure_gate


# ---- #3: harness-skill detection must read TOP-LEVEL target_profile (the epiphany-plan shape) ----
def test_detection_reads_top_level_target_profile():
    plan = {"target_profile": "harness_skill", "steps": []}
    assert closure_gate.is_harness_skill_build(plan) is True


def test_detection_still_reads_nested_plan_meta():
    plan = {"plan_meta": {"target_profile": "harness_skill"}, "steps": []}
    assert closure_gate.is_harness_skill_build(plan) is True


def test_detection_false_for_non_harness_plan():
    assert closure_gate.is_harness_skill_build({"target_profile": "library", "steps": []}) is False


# ---- #4: enforce_closure must DISCOVER an authored wiring-contract in the skill package ----
def test_enforce_closure_discovers_package_authored_contract(tmp_path, monkeypatch):
    calls = {}

    def fake_gate(skill_pkg, *, contract=None, plan=None):
        calls["contract"] = str(contract) if contract else None
        calls["plan"] = str(plan) if plan else None
        return {"route": "done", "gate": {"used": "authored"}}

    monkeypatch.setattr(closure_gate, "gate_coverage_to_done", fake_gate)
    monkeypatch.setattr(closure_gate, "_WIRING_AVAILABLE", True, raising=False)
    pkg = tmp_path / "skill"
    pkg.mkdir()
    (pkg / "wiring-contract.yaml").write_text("wiring_contract: []\n")
    plan = {"target_profile": "harness_skill", "steps": []}
    res = closure_gate.enforce_closure(plan, str(pkg), plan_path=str(tmp_path / "plan.json"))
    # it used the package's authored contract, NOT the noisy bootstrapped plan fallback
    assert calls["contract"] and calls["contract"].endswith("wiring-contract.yaml")
    assert calls["plan"] is None
    assert res["route"] == "done"


# ---- bootstrap scaffold: per-step DoD checklist + REAL coverage gate + empty-criteria guard ----
def _plan(tmp_path, steps):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"target_profile": "harness_skill", "steps": steps,
                             "requirement_ledger": {}}))
    return str(p)


def test_scaffold_writes_checklist_and_runs_coverage(tmp_path):
    steps = [{"id": "S1", "goal": "do x", "acceptance_criteria": ["x holds"],
              "integration_checks": [], "outputs": ["x"], "traces_requirements": ["R1"]}]
    res = bootstrap.scaffold_session(_plan(tmp_path, steps), str(tmp_path / "sess"))
    assert res["steps"] == 1
    assert res["empty_criteria_steps"] == []
    sj = os.path.join(res["session"], "steps.jsonl")
    rows = [json.loads(line) for line in open(sj)]
    assert rows[0]["dod_verdict"] == "PENDING" and rows[0]["dod_evidence"] is None
    assert "coverage" in res


def test_scaffold_blocks_on_empty_acceptance_criteria(tmp_path):
    steps = [{"id": "S1", "goal": "no criteria", "acceptance_criteria": []}]
    res = bootstrap.scaffold_session(_plan(tmp_path, steps), str(tmp_path / "sess"))
    assert "S1" in res["empty_criteria_steps"]
    assert res["start_gate"] == "BLOCKED"   # empty acceptance => never an auto-pass (verify_dod gate)


def test_close_session_routes_done_for_nonharness(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"target_profile": "library", "steps": []}))
    res = bootstrap.close_session(str(p), str(tmp_path / "sess"))
    assert res["route"] == "done"   # N/A closure for a non-harness plan
