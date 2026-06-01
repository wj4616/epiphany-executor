"""P7: substrate co-deliverables are available + CV-07 Workflow reproduces --serial; S-P7-handoff
is a tracked non-blocking item."""
import pytest

from epiphany_executor.benchmark import held_out_plans
from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.scheduler import build_dag, schedule_waves

wc = pytest.importorskip("goatcs_harness.workflow_compile")
el = pytest.importorskip("goatcs_harness.effect_ledger")
wt = pytest.importorskip("goatcs_harness.worktree")


def test_substrate_primitives_available_in_harness():
    # AX-06 / AX-08 / DF-3 landed UPSTREAM (reuse, not skill-local)
    assert hasattr(wc, "compile_workflow")
    assert hasattr(el, "EffectLedger") and hasattr(el, "EffectClass")
    assert hasattr(wt, "WorktreeSubstrate")


def test_cv07_compiled_workflow_reproduces_serial():
    plan = held_out_plans()["ho-parallel"]
    contracts = {s["step_id"]: stamp_node_contract(s) for s in plan["steps"]}
    dag = build_dag(contracts)
    compiled = wc.compile_workflow(dag)
    serial_order = [sid for w in schedule_waves(contracts, serial=True) for sid in w.all_steps]
    assert compiled.reproduces_serial(serial_order)   # CV-07: else label advisory/NON-GOAL


def test_effect_ledger_unlocks_irreversible_auto_resume(tmp_path):
    # the v2-enabling primitive: an irreversible effect WITH an idempotency token replays safely
    led = el.EffectLedger(str(tmp_path / "e.jsonl"))
    e = el.Effect("deploy", el.EffectClass.EXTERNALLY_IRREVERSIBLE, idempotency_token="tok", payload={})
    n = {"c": 0}
    led.perform_once(e, lambda _e: n.__setitem__("c", n["c"] + 1))
    el.EffectLedger(str(tmp_path / "e.jsonl")).perform_once(e, lambda _e: n.__setitem__("c", n["c"] + 1))
    assert n["c"] == 1     # committed -> not re-performed on resume (no double-apply)
