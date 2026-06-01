"""IC-P0c: a compiled node carries lifecycle + DoD + effect + traces contract fields,
on BOTH the real emitted shape and the plan.schema.json shape (INV-18)."""
import json
import pathlib

import pytest

from epiphany_executor.contract_template import (
    CONTRACT_FIELD_GROUPS,
    assert_node_contract,
    stamp_node_contract,
)

REAL_RUN = pathlib.Path(
    "/home/myuser/docs/goatcs-output/epiphany-plan-runs/"
    "2026-05-31-goatcs-v3-build-plan/goatcs-v3-build-execution-plan.json"
)


def test_stamps_all_four_field_groups_on_real_emitted_step():
    plan = json.loads(REAL_RUN.read_text())
    step = plan["steps"][0]  # real shape: traces_to, integration_checks object, bare deps
    contract = stamp_node_contract(step)
    for group in CONTRACT_FIELD_GROUPS:
        assert group in contract
    assert_node_contract(contract)
    assert contract["step_id"] == step["step_id"]
    assert contract["lifecycle"]["state"] == "UNSTARTED"
    assert contract["effect"]["effect_class"] == "unclassified"


def test_integration_checks_object_is_tolerated():
    # real emit: integration_checks is a single object {id,assert,status}
    step = {"step_id": "s1", "acceptance_criteria": ["x passes"],
            "integration_checks": {"id": "IC-1", "assert": "y", "status": "UNVERIFIED"}}
    c = stamp_node_contract(step)
    assert isinstance(c["dod"]["integration_checks"], list)
    assert c["dod"]["integration_checks"][0]["id"] == "IC-1"
    assert c["dod"]["verifiable"] is True


def test_traces_to_and_traces_requirements_both_map():
    a = stamp_node_contract({"step_id": "a", "traces_to": ["INV-1"]})
    b = stamp_node_contract({"step_id": "b", "traces_requirements": ["INV-1"]})
    assert a["traces"] == ["INV-1"]
    assert b["traces"] == ["INV-1"]


def test_bare_string_deps_become_ordering_prereqs():
    c = stamp_node_contract({"step_id": "s", "dependencies": ["s0", "s1"]})
    assert all(d["edge_class"] == "ordering" and d["from_typed"] is False
               for d in c["dependencies"])
    assert {d["on"] for d in c["dependencies"]} == {"s0", "s1"}


def test_typed_deps_preserve_edge_class():
    c = stamp_node_contract({"step_id": "s", "dependencies": [
        {"on": "s0", "kind": "data", "edge_class": "implementation-prerequisite"}]})
    assert c["dependencies"][0]["edge_class"] == "implementation-prerequisite"
    assert c["dependencies"][0]["from_typed"] is True


def test_undeclared_outputs_conflict_with_all():
    c = stamp_node_contract({"step_id": "s", "acceptance_criteria": ["ok"]})
    assert c["effect"]["footprint"]["conflicts_with_all"] is True


def test_declared_outputs_set_footprint():
    c = stamp_node_contract({"step_id": "s", "outputs": ["src/a.py", "src/b.py"],
                             "acceptance_criteria": ["ok"]})
    assert set(c["effect"]["footprint"]["declared_outputs"]) == {"src/a.py", "src/b.py"}
    assert c["effect"]["footprint"]["conflicts_with_all"] is False


def test_empty_acceptance_is_unverifiable_inv10():
    c = stamp_node_contract({"step_id": "s"})  # no criteria at all
    assert c["dod"]["verifiable"] is False


def test_unknown_keys_preserved_inv2():
    c = stamp_node_contract({"step_id": "s", "weird_new_field": 42})
    assert c["extra"]["weird_new_field"] == 42


def test_missing_step_id_fails_closed():
    with pytest.raises(ValueError):
        stamp_node_contract({"goal": "no id"})
