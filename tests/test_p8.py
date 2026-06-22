"""P8: Memory flywheel (IC-P8l, CV-07), V-battery (IC-P8), self-host (IC-P8s)."""
import pytest

from epiphany_executor.context_builder import ThinkingTier, apply_memory_priors
from epiphany_executor.memory import (
    Prior,
    PriorStore,
    distill_priors,
    prior_to_scheduling_hint,
)

# ----- S-P8-learn (Memory flywheel) -----


def test_priors_versioned_and_revocable(tmp_path):
    store = PriorStore(str(tmp_path / "priors.json"))
    store.put(Prior(key="antichain_widths", kind="plan-shape", value=[1, 3, 1], source_run="r1"))
    store.put(Prior(key="antichain_widths", kind="plan-shape", value=[1, 4, 1], source_run="r2"))
    assert store.priors["antichain_widths"].version == 2          # version-bumped
    store.revoke("antichain_widths")
    assert "antichain_widths" not in store.active()                # revocable
    store.save()
    assert PriorStore(str(tmp_path / "priors.json")).load().priors["antichain_widths"].revoked


def test_empty_memory_is_failsafe():
    # a run with empty/None memory is still correct: apply_memory_priors is a no-op
    assert apply_memory_priors(ThinkingTier.STANDARD, None) == (ThinkingTier.STANDARD, [])
    assert prior_to_scheduling_hint(PriorStore("/nonexistent/x.json")) == {}


def test_cv07_prior_measurably_alters_allocation(tmp_path):
    # CV-07: a flywheel entry measurably alters a subsequent run's thinking-budget
    store = PriorStore(str(tmp_path / "p.json"))
    store.put(Prior(key="budget_calibration", kind="budget-calibration",
                    value={"suggested_tier": "deep"}, source_run="r1"))
    hint = prior_to_scheduling_hint(store)
    assert hint == {"suggested_tier": "deep"}
    raised, note = apply_memory_priors(ThinkingTier.MINIMAL, hint)
    assert raised == ThinkingTier.DEEP and note                    # measurably altered (raised)


def test_priors_are_advisory_raise_only(tmp_path):
    # a prior may NOT lower a tier below its safety floor (advisory raise-only)
    store = PriorStore(str(tmp_path / "p.json"))
    store.put(Prior(key="budget_calibration", kind="budget-calibration",
                    value={"suggested_tier": "minimal"}, source_run="r1"))
    hint = prior_to_scheduling_hint(store)
    lowered, note = apply_memory_priors(ThinkingTier.DEEP, hint)
    assert lowered == ThinkingTier.DEEP and note == []             # cannot lower below floor


def test_distill_priors_from_ledger():
    led = [{"kind": "lifecycle-transition", "node": "s2", "lifecycle_state": "FAILED"}]
    priors = distill_priors(led, run_id="run-x", antichain_widths=[1, 3, 1])
    keys = {p.key for p in priors}
    assert "failure_signatures" in keys and "antichain_widths" in keys
    fs = next(p for p in priors if p.key == "failure_signatures")
    assert fs.value == ["s2"] and fs.source_run == "run-x"


# ----- S-P8-reverify (V-battery) -----


def test_v_battery_passes():
    # skip_suite=True avoids the suite-running-the-suite recursion; the CLI run covers V5.
    vb = pytest.importorskip("tools.v_battery", reason="run from repo root")
    res = vb.run_v_battery(skip_suite=True)
    assert res.passed, [c for c in res.checks if not c["ok"]]


# ----- S-P8-selfhost -----


def test_selfhost_reaches_clean_terminal():
    sh = pytest.importorskip("tools.selfhost")
    rep = sh.run_selfhost()
    assert rep["gate"] == "PROCEED"
    assert rep["terminal"] == "CLEAN"
    assert rep["clean_terminal"] is True
    assert rep["inv12_no_silent_bypass"] is True
    assert rep["dryrun_sandboxed"] >= 1          # S-P0 forge / S-P7 promote sandboxed (PC-17)
