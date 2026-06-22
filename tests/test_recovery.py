"""S-P3-recovery IC-P3r: R-023 forced-fail halts + checkpoints + offers recovery with the step
NOT complete; mid-wave fail discards staged siblings + committed state stays at the pre-wave
checkpoint; irreversible rollback forbidden (INV-7)."""
from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.lifecycle import LifecycleState
from epiphany_executor.recovery import (
    RecoveryOption,
    on_verify_fail,
    recovery_menu,
    wave_rollback,
)


def _c(step_id, outputs=()):
    return stamp_node_contract({"step_id": step_id, "acceptance_criteria": ["ok"],
                                "outputs": list(outputs)})


def test_r023_forced_fail_halts_step_not_accepted():
    halt = on_verify_fail(_c("s", outputs=["src/s.py"]), checkpoint_seq=7)
    assert halt.lifecycle_state == LifecycleState.FAILED
    assert halt.not_accepted is True
    assert halt.checkpoint_seq == 7
    assert RecoveryOption.HALT_FOR_HUMAN in halt.menu
    assert RecoveryOption.RETRY in halt.menu


def test_reversible_step_offers_rollback():
    menu = recovery_menu(_c("s", outputs=["src/s.py"]), downstream_safe=True)
    assert RecoveryOption.ROLLBACK in menu
    assert RecoveryOption.SKIP_WITH_WAIVER in menu      # downstream-safe -> skip offered


def test_irreversible_rollback_forbidden():
    halt = on_verify_fail(_c("s", outputs=["https://deploy/prod"]), checkpoint_seq=3)
    assert halt.forbidden_rollback is True
    assert RecoveryOption.ROLLBACK not in halt.menu     # cannot roll back an irreversible effect


def test_not_downstream_safe_hides_skip():
    menu = recovery_menu(_c("s", outputs=["src/s.py"]), downstream_safe=False)
    assert RecoveryOption.SKIP_WITH_WAIVER not in menu


def test_wave_rollback_discards_staged_and_keeps_pre_wave_checkpoint():
    discarded = []
    res = wave_rollback(["<wt:a>", "<wt:b>", "<wt:c>"], pre_wave_checkpoint_seq=5,
                        discard_fn=discarded.append)
    assert res.discarded_worktrees == ["<wt:a>", "<wt:b>", "<wt:c>"]
    assert discarded == ["<wt:a>", "<wt:b>", "<wt:c>"]   # all staged siblings discarded
    assert res.recovery_checkpoint_seq == 5              # pre-wave checkpoint stands
    assert res.committed_state_advanced is False         # no partial wave persisted (CV-01)
