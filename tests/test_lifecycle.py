"""S-P3-lifecycle IC-P3l: kill+resume reconstructs lifecycle from the ledger; no ACCEPTED step
re-runs; persistence reuses the harness Burr/ledger symbols; legal transitions; multi-irreversible
flag (F-13)."""
import pytest

from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.lifecycle import (
    BarrierCommit,
    IllegalTransition,
    LifecycleState,
    LifecycleStore,
    RecoveryCursor,
    is_multi_irreversible,
    make_burr_checkpoint,
    transition,
)


def test_legal_and_illegal_transitions():
    assert transition(LifecycleState.UNSTARTED, LifecycleState.IN_FLIGHT) == LifecycleState.IN_FLIGHT
    assert transition(LifecycleState.IN_FLIGHT, LifecycleState.VERIFIED) == LifecycleState.VERIFIED
    assert transition(LifecycleState.VERIFIED, LifecycleState.ACCEPTED) == LifecycleState.ACCEPTED
    with pytest.raises(IllegalTransition):
        transition(LifecycleState.UNSTARTED, LifecycleState.ACCEPTED)   # cannot skip
    with pytest.raises(IllegalTransition):
        transition(LifecycleState.ACCEPTED, LifecycleState.IN_FLIGHT)   # no silent re-open (INV-7)


def test_kill_resume_folds_ledger(tmp_path):
    led = str(tmp_path / "ledger.jsonl")
    store = LifecycleStore(led)
    store.record(RecoveryCursor("s1", LifecycleState.IN_FLIGHT, 0))
    store.record(RecoveryCursor("s1", LifecycleState.ACCEPTED, 2))
    store.record(RecoveryCursor("s2", LifecycleState.IN_FLIGHT, 1))
    # simulate a fresh process: new store over the same ledger reconstructs current state
    resumed = LifecycleStore(led).fold()
    assert resumed["s1"].lifecycle_state == LifecycleState.ACCEPTED
    assert resumed["s1"].effect_ledger_cursor == 2
    assert resumed["s2"].lifecycle_state == LifecycleState.IN_FLIGHT


def test_accepted_steps_not_rerun(tmp_path):
    led = str(tmp_path / "ledger.jsonl")
    store = LifecycleStore(led)
    store.record(RecoveryCursor("done", LifecycleState.ACCEPTED, 1))
    store.record(RecoveryCursor("todo", LifecycleState.IN_FLIGHT, 0))
    assert store.accepted_steps() == {"done"}   # resume scheduler skips these (INV-5)


def test_persistence_reuses_burr_symbol(tmp_path):
    # INV-3: make_burr_checkpoint returns the harness SQLitePersister (not a private store)
    from goatcs_harness.persist import SQLitePersister
    p = make_burr_checkpoint(str(tmp_path / "burr.db"))
    assert isinstance(p, SQLitePersister)


def test_multi_irreversible_flagged():
    multi = stamp_node_contract({"step_id": "x", "acceptance_criteria": ["ok"],
                                 "outputs": ["https://deploy/a", "publish to b"]})
    single = stamp_node_contract({"step_id": "y", "acceptance_criteria": ["ok"],
                                  "outputs": ["https://deploy/a"]})
    local = stamp_node_contract({"step_id": "z", "acceptance_criteria": ["ok"],
                                 "outputs": ["src/a.py"]})
    assert is_multi_irreversible(multi) is True
    assert is_multi_irreversible(single) is False
    assert is_multi_irreversible(local) is False


def test_barrier_commit_orders_by_build_order():
    bc = BarrierCommit(build_order=["a", "b", "c"])
    cursors = [RecoveryCursor("c", LifecycleState.ACCEPTED),
               RecoveryCursor("a", LifecycleState.ACCEPTED),
               RecoveryCursor("b", LifecycleState.ACCEPTED)]
    ordered = [c.step_id for c in bc.order_cursors(cursors)]
    assert ordered == ["a", "b", "c"]
