"""P6: corpus partition (IC-P6corp), baseline (IC-P6base), validate gate (IC-P6v),
3-arm benchmark (IC-P6b, R-018, CV-06)."""
import tempfile

import pytest

from epiphany_executor.baseline import BASELINE_CAPABILITIES, run_baseline
from epiphany_executor.benchmark import (
    executor_beats_baseline,
    held_out_plans,
    jury_veto_self_test,
    run_baseline_arm,
    run_benchmark,
    run_executor_arm,
)
from epiphany_executor.corpus import partition_corpus
from epiphany_executor.validate import validate_corpus

# ----- S-P6-corpus -----


def test_partition_is_disjoint_and_marks_correct_halt():
    part = partition_corpus()
    assert part.disjoint
    # the 3 real gate-FAIL JSON runs are marked correct-halt
    halts = {p.name for p in part.tuning if p.disposition == "correct-halt"}
    assert any("goatcs-v3" in h for h in halts)


# ----- S-P6-baseline -----


def test_baseline_capabilities_are_minimal():
    assert BASELINE_CAPABILITIES["checks_acceptance"] is True
    for absent in ("look_ahead", "back_update", "wave_parallel", "checkpoint_resume",
                   "effect_taxonomy", "coverage_closure"):
        assert BASELINE_CAPABILITIES[absent] is False


def test_baseline_applies_and_checks_and_halts_on_failure():
    plan = {"steps": [{"step_id": "a"}, {"step_id": "b"}, {"step_id": "c"}]}
    ok = run_baseline(plan, apply_fn=lambda s: {}, check_fn=lambda s, a: True)
    assert ok.end_to_end_success and ok.accepted == ["a", "b", "c"]
    fail = run_baseline(plan, apply_fn=lambda s: {}, check_fn=lambda s, a: s["step_id"] != "b")
    assert fail.failed_at == "b" and fail.accepted == ["a"]   # halts, no recovery


# ----- S-P6-benchmark -----


def test_jury_veto_self_test():
    assert jury_veto_self_test() is True       # CV-06: jury catches the seeded bad output


def test_baseline_scores_zero_on_decisive_trio():
    plan = held_out_plans()["ho-serial"]
    b = run_baseline_arm(plan)
    sv = b.score_vector()
    assert sv["m3_back_update"] == 0.0 and sv["m5_recovery"] == 0.0 and sv["m6_coverage"] == 0.0


def test_executor_beats_baseline_on_decisive_trio(tmp_path):
    plan = held_out_plans()["ho-parallel"]
    base = run_baseline_arm(plan)
    wave = run_executor_arm(plan, serial=False, jury=3, ledger_dir=str(tmp_path))
    v = executor_beats_baseline(base, wave)
    assert v["decisive_trio_won"] and v["passes_R018"] and v["no_regressions"]


def test_wave_arm_has_fewer_barriers_on_parallel_plan(tmp_path):
    plan = held_out_plans()["ho-parallel"]
    base = run_baseline_arm(plan)
    wave = run_executor_arm(plan, serial=False, jury=1, ledger_dir=str(tmp_path))
    assert wave.n_barriers < base.n_barriers   # throughput gain via wave parallelism


def test_full_benchmark_all_plans_pass_r018(tmp_path):
    rep = run_benchmark(held_out_plans(), str(tmp_path))
    assert rep.jury_veto_self_test_passed
    assert rep.all_plans_pass_R018


# ----- S-P6-validate (BLOCKING GATE) -----


def test_validate_real_corpus_all_ok():
    pytest.importorskip("goatcs_harness.loader")
    part = partition_corpus()
    rep = validate_corpus(part.tuning)
    assert rep.all_ok, [r.name for r in rep.results if not r.ok]
    assert rep.routed == []                      # no ingest failures routed to co-tuning


def test_gate_fail_run_halts_correctly():
    pytest.importorskip("goatcs_harness.loader")
    part = partition_corpus()
    g = [r for r in validate_corpus(part.tuning).results if "goatcs-v3-build-plan" in r.name]
    assert g and g[0].gate_decision == "HALT" and g[0].ok    # INV-17 correct-halt
