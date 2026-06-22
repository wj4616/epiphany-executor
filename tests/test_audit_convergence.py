"""Convergence-audit fixes: GH-1 (importer stamp ≡ skill stamp — drift pin) + EX-1 (reconcile
orphan-module guard)."""
import glob
import json
import os

import pytest

from epiphany_executor.contract_template import stamp_node_contract

GOATCS_V3 = glob.glob("/home/myuser/docs/goatcs-output/epiphany-plan-runs/"
                      "2026-05-31-goatcs-v3-build-plan/*execution-plan.json")


# ----- GH-1: the harness importer stamp must agree with the skill's contract template -----


def _assert_same_contract(a: dict, b: dict):
    assert a["lifecycle"]["state"] == b["lifecycle"]["state"]
    for k in ("acceptance_criteria", "integration_checks", "outputs"):
        assert a["dod"][k] == b["dod"][k], k
    assert a["effect"]["footprint"]["declared_outputs"] == b["effect"]["footprint"]["declared_outputs"]
    assert a["effect"]["footprint"]["conflicts_with_all"] == b["effect"]["footprint"]["conflicts_with_all"]
    assert a["traces"] == b["traces"]


def test_harness_stamp_matches_skill_stamp_on_synthetic():
    epi = pytest.importorskip("goatcs_harness.epiphany_plan_importer")
    step = {"step_id": "s1", "goal": "g", "acceptance_criteria": ["pytest exits 0"],
            "integration_checks": {"id": "IC", "assert": "x", "status": "UNVERIFIED"},
            "outputs": ["src/a.py"], "dependencies": ["s0"], "traces_to": ["INV-1"]}
    _assert_same_contract(epi.stamp_step_contract(step), stamp_node_contract(step))


@pytest.mark.skipif(not GOATCS_V3, reason="real run fixture not present")
def test_harness_stamp_matches_skill_stamp_on_real_run():
    epi = pytest.importorskip("goatcs_harness.epiphany_plan_importer")
    plan = json.loads(open(GOATCS_V3[0]).read())
    for step in plan["steps"][:15]:
        _assert_same_contract(epi.stamp_step_contract(step), stamp_node_contract(step))


# ----- EX-1: reconcile skips orphan modules not referenced by the preserved graph -----


def test_reconcile_skips_orphan_modules(tmp_path):
    from tools.reconcile_forge import reconcile
    live = tmp_path / "live"
    (live / "modules").mkdir(parents=True)
    # live graph references only modules/N-a.md
    (live / "graph.json").write_text(json.dumps(
        {"nodes": {"a": {"module_file": "modules/N-a.md"}}}))
    staging = tmp_path / "staging"
    (staging / "modules").mkdir(parents=True)
    (staging / "modules" / "N-a.md").write_text("a")          # referenced -> add
    (staging / "modules" / "N-orphan.md").write_text("orphan")  # NOT referenced -> skip
    (staging / "newfile.txt").write_text("x")                 # non-module -> add
    res = reconcile(str(staging), str(live))
    assert "modules/N-orphan.md" in res["skipped_orphans"]
    assert "modules/N-a.md" in res["added"]
    assert "newfile.txt" in res["added"]
    assert not (live / "modules" / "N-orphan.md").exists()    # orphan not written


def test_reconcile_first_emit_adds_everything(tmp_path):
    # no live graph.json -> no orphan filtering (first emit)
    from tools.reconcile_forge import reconcile
    live = tmp_path / "live"
    live.mkdir()
    staging = tmp_path / "staging"
    (staging / "modules").mkdir(parents=True)
    (staging / "modules" / "N-anything.md").write_text("x")
    res = reconcile(str(staging), str(live))
    assert res["n_skipped_orphans"] == 0
    assert "modules/N-anything.md" in res["added"]
