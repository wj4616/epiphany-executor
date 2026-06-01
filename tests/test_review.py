"""S-P4-review IC-P4: back-update is append-only + bounded; an upstream change makes the
downstream step consume REFRESHED look-ahead before running (INV-11); sentinel only appends and
is 1-firing + quiesces in-flight (CV-04)."""
import pytest

from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.lifecycle import LifecycleState, RecoveryCursor
from epiphany_executor.review import (
    BackUpdateBudget,
    BackUpdateExhausted,
    ConvergenceTracker,
    IrreversibleUndoForbidden,
    Sentinel,
    back_update,
    compute_state_delta,
    propagate_forward_delta,
    reopen_cursor,
)


def _c(step_id, outputs=()):
    return stamp_node_contract({"step_id": step_id, "acceptance_criteria": ["ok"],
                                "outputs": list(outputs)})


def test_state_delta():
    d = compute_state_delta({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
    assert d["changed"] == {"b": {"from": 2, "to": 3}}
    assert d["added"] == {"c": 4}
    assert d["removed"] == []


def test_back_update_is_append_only():
    appended = []
    bu = back_update(_c("prior", outputs=["src/p.py"]), {"reason": "upstream changed"},
                     depth=1, budget=BackUpdateBudget(), ledger_append=appended.append)
    assert bu.reopened is True
    assert len(appended) == 1
    assert appended[0]["kind"] == "back-update-correcting-delta"   # a NEW entry, not a mutation
    assert appended[0]["reopen"] == "needs-re-verify"


def test_back_update_bounded_by_depth():
    with pytest.raises(BackUpdateExhausted):
        back_update(_c("p", outputs=["src/p.py"]), {}, depth=99,
                    budget=BackUpdateBudget(max_depth=5), ledger_append=lambda e: None)


def test_back_update_total_budget_exhausts():
    b = BackUpdateBudget(max_total=2)
    for _ in range(2):
        back_update(_c("p", outputs=["src/p.py"]), {}, depth=1, budget=b, ledger_append=lambda e: None)
    with pytest.raises(BackUpdateExhausted):
        back_update(_c("p", outputs=["src/p.py"]), {}, depth=1, budget=b, ledger_append=lambda e: None)


def test_irreversible_back_update_forbidden():
    with pytest.raises(IrreversibleUndoForbidden):
        back_update(_c("p", outputs=["https://deploy/prod"]), {}, depth=1,
                    budget=BackUpdateBudget(), ledger_append=lambda e: None)


def test_reopen_accepted_is_explicit_amended_then_inflight():
    seq = reopen_cursor(RecoveryCursor("s", LifecycleState.ACCEPTED, 3))
    states = [c.lifecycle_state for c in seq]
    assert states == [LifecycleState.AMENDED, LifecycleState.IN_FLIGHT]   # never silent (INV-7)


def test_forward_delta_marks_successors_stale_inv11():
    dag = {"a": set(), "b": {"a"}, "c": {"b"}}
    assert propagate_forward_delta(dag, "a") == {"b"}      # b must refresh look-ahead before run
    assert propagate_forward_delta(dag, "b") == {"c"}


def test_convergence_tracker():
    t = ConvergenceTracker()
    t.record_round(3); t.record_round(1); t.record_round(0)
    assert t.converged is True
    t.record_round(2)
    assert t.converged is False


def test_sentinel_only_appends_and_is_1_firing():
    s = Sentinel()
    appended = []
    # step 'x' regresses (reassert returns False)
    sig1 = s.sweep(["x"], lambda sid: False, wave_in_flight=False, ledger_append=appended.append)
    assert len(sig1) == 1 and sig1[0].regressed_step == "x"
    assert appended[0]["kind"] == "sentinel-regression-forward-delta"   # append-only
    # same epoch, same regression -> NOT re-fired (1-firing latch, CV-04)
    sig2 = s.sweep(["x"], lambda sid: False, wave_in_flight=False, ledger_append=appended.append)
    assert sig2 == []
    assert len(appended) == 1


def test_sentinel_quiesces_while_wave_in_flight():
    s = Sentinel()
    appended = []
    sig = s.sweep(["x"], lambda sid: False, wave_in_flight=True, ledger_append=appended.append)
    assert sig == [] and appended == []        # cannot re-fire against an active wave (CV-04)


def test_sentinel_refires_in_new_epoch():
    s = Sentinel()
    appended = []
    s.sweep(["x"], lambda sid: False, wave_in_flight=False, ledger_append=appended.append)
    s.advance_epoch()
    sig = s.sweep(["x"], lambda sid: False, wave_in_flight=False, ledger_append=appended.append)
    assert len(sig) == 1 and len(appended) == 2    # a genuinely new regression epoch may re-fire
