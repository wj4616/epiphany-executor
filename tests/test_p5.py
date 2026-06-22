"""P5 acceptance: effect-class (IC-P5e), drift (IC-P5d), coverage (IC-P5c), telemetry (IC-P5t)."""
import pytest

from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.coverage import coverage_report, waive_plan_caused_orphan
from epiphany_executor.drift import DriftResolution, check_drift, snapshot_hashes
from epiphany_executor.effect_class import (
    AutoResumeNotAvailable,
    EffectClass,
    auto_resume_irreversible,
    classify_command,
    gating_decision,
    step_is_gated,
)
from epiphany_executor.lifecycle import LifecycleState
from epiphany_executor.telemetry import (
    HaltClass,
    halt_resolution,
    health_view,
    resume_brief,
    resume_from_halt,
)

# ----- S-P5-effect-class IC-P5e -----


def test_classification_is_pre_execution_and_conservative():
    assert classify_command("cat file.txt") == EffectClass.PURE
    assert classify_command("echo hi > out.txt") == EffectClass.LOCAL_MUTATING
    assert classify_command("curl https://api/deploy") == EffectClass.EXTERNALLY_IRREVERSIBLE
    assert classify_command("frobnicate the doohickey") == EffectClass.EXTERNALLY_IRREVERSIBLE  # default


def test_irreversible_without_token_is_gated():
    g = gating_decision(EffectClass.EXTERNALLY_IRREVERSIBLE, has_idempotency_token=False)
    assert g.gated is True
    g2 = gating_decision(EffectClass.EXTERNALLY_IRREVERSIBLE, has_idempotency_token=True)
    assert g2.gated is False
    assert gating_decision(EffectClass.LOCAL_MUTATING).gated is False


def test_step_with_irreversible_action_is_gated():
    c = stamp_node_contract({"step_id": "s", "acceptance_criteria": ["ok"],
                             "actions": ["edit src/a.py", "git push origin main"]})
    assert step_is_gated(c) is True


def test_v1_auto_resume_branch_is_unreachable():
    with pytest.raises(AutoResumeNotAvailable):
        auto_resume_irreversible("anything")


# ----- S-P5-drift IC-P5d -----


def test_started_step_text_edit_halts():
    plan = {"plan_id": "p", "steps": [{"step_id": "s1", "goal": "do X", "actions": ["a"]}]}
    snap = snapshot_hashes(plan)
    edited = {"plan_id": "p", "steps": [{"step_id": "s1", "goal": "do Y", "actions": ["a"]}]}
    v = check_drift(snap, edited, lifecycle={"s1": LifecycleState.ACCEPTED})
    assert v.resolution == DriftResolution.HALT
    assert "s1" in v.halt_steps


def test_whitespace_change_does_not_false_trip():
    plan = {"plan_id": "p", "steps": [{"step_id": "s1", "goal": "do  X", "actions": ["a"]}]}
    snap = snapshot_hashes(plan)
    ws = {"plan_id": "p", "steps": [{"step_id": "s1", "goal": "do X", "actions": ["a"]}]}  # ws only
    v = check_drift(snap, ws, lifecycle={"s1": LifecycleState.ACCEPTED})
    assert v.resolution == DriftResolution.NONE


def test_unstarted_drift_reimports():
    plan = {"plan_id": "p", "steps": [{"step_id": "s1", "goal": "X"}]}
    snap = snapshot_hashes(plan)
    edited = {"plan_id": "p", "steps": [{"step_id": "s1", "goal": "Z"}]}
    v = check_drift(snap, edited, lifecycle={"s1": LifecycleState.UNSTARTED})
    assert v.resolution == DriftResolution.REIMPORT


# ----- S-P5-coverage IC-P5c -----


def test_executor_caused_orphan_blocks():
    # plan says req R1 maps to step s1, but s1 does NOT trace R1 -> executor dropped a trace
    plan = {"steps": [{"step_id": "s1", "traces_to": ["R2"]}],
            "gate_status": {"requirement_to_step_map": {"R1": "s1"}},
            "requirement_preservation": {"input_obligations": ["R1", "R2"]}}
    rep = coverage_report(plan)
    assert rep.blocks is True
    assert any(o.kind == "executor-caused" and o.requirement == "R1" for o in rep.orphans)


def test_plan_caused_orphan_is_waivable_with_ack():
    plan = {"steps": [{"step_id": "s1", "traces_to": ["R2"]}],
            "requirement_preservation": {"input_obligations": ["R1", "R2"]}}  # R1 never assigned
    rep = coverage_report(plan)
    assert rep.blocks is False           # plan-caused alone does not release-block
    orphan = rep.plan_caused[0]
    assert orphan.requirement == "R1"
    w = waive_plan_caused_orphan(orphan, operator_ack=True)
    assert w.operator_ack and w.routed_to == "epiphany-plan"
    with pytest.raises(ValueError):
        waive_plan_caused_orphan(orphan, operator_ack=False)   # ack required (F-10)


# ----- S-P5-telemetry IC-P5t -----


def test_health_view_from_ledger():
    led = [
        {"kind": "lifecycle-transition", "node": "a", "lifecycle_state": "ACCEPTED"},
        {"kind": "lifecycle-transition", "node": "b", "lifecycle_state": "FAILED"},
        {"kind": "back-update-correcting-delta", "node": "a"},
        {"verdict": "PASS"}, {"verdict": "FAIL"},
    ]
    hv = health_view(led, total_steps=3, coverage_pct=0.66, resident_mode="hold-all",
                     fanout={"max_concurrent_effectors": 4, "max_jury_width": 3, "speculative_count": 2})
    assert hv.accepted == 1 and hv.failed == 1 and hv.back_edge_churn == 1
    assert hv.verify_pass_rate == 0.5 and hv.est_remaining == 2
    assert hv.max_concurrent_effectors == 4 and hv.speculative_count == 2


def test_resume_brief_is_self_contained():
    hv = health_view([], total_steps=10)
    b = resume_brief("plan-x", hv, ["s3", "s4"], graph_sha="abc", session_dir="/tmp/sess")
    assert b["self_contained"] and b["plan_id"] == "plan-x"
    assert b["next_steps"] == ["s3", "s4"]
    assert "--resume /tmp/sess" in b["how_to_resume"]


def test_halt_resumes_after_recorded_decision():
    res = halt_resolution(HaltClass.DEFECT_ACK)
    assert "override-and-proceed" in res.choices
    run = resume_from_halt(HaltClass.DEFECT_ACK, "override-and-proceed", "/tmp/sess")
    assert run.resolved and "--resume /tmp/sess" in run.resume_entry
    with pytest.raises(ValueError):
        resume_from_halt(HaltClass.DEFECT_ACK, "bogus-choice", "/tmp/sess")
