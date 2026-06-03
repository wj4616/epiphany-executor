"""End-to-end ingest of the real epiphany-report plan (BD-4 gate-semantics reconciliation).

Guards the epiphany-plan <-> epiphany-executor integration against the regression where a clean,
PASSing epiphany-plan Markdown plan was falsely HALTed because epiphany-plan marks its
coverage/structural gates as blocking-TYPE (``- **blocking:** true``) even on PASS. The executor
must read the VERDICT (PASS -> OPEN -> PROCEED), not the blocking-nature flag, and must split
comma-separated requirement traces into individual ids for the coverage matrix.
"""
from __future__ import annotations

import os

import pytest

from epiphany_executor.gate_defect import evaluate_gate
from epiphany_executor.md_normalizer import normalize_plan_md

_PLAN = os.path.expanduser("~/docs/solution/2026-05-31-3-ai/plan.md")


@pytest.fixture(scope="module")
def real_plan():
    if not os.path.exists(_PLAN):
        pytest.skip(f"real epiphany-report plan not present at {_PLAN}")
    plan, lossy = normalize_plan_md(open(_PLAN, encoding="utf-8").read())
    return plan, lossy


def test_real_plan_ingests_without_loss(real_plan):
    plan, lossy = real_plan
    assert len(plan["steps"]) == 48
    assert lossy == []                      # schema-conformant MD -> no lossy degradation


def test_passing_blocking_type_gate_is_OPEN_not_BLOCKING(real_plan):
    """The plan's Coverage Verdict is PASS with ``blocking: true`` (blocking-TYPE gate).
    The gate level must be OPEN (the gate passed), NOT BLOCKING."""
    plan, _ = real_plan
    assert plan["gate_status"]["verdict"] == "PASS"
    assert plan["gate_status"]["gate"] == "OPEN"


def test_clean_plan_PROCEEDs_not_HALT(real_plan):
    """INV-17 start gate must PROCEED on the clean PASS plan (the false-halt regression)."""
    plan, _ = real_plan
    decision = evaluate_gate(plan)
    assert decision.decision == "PROCEED", decision.reasons
    assert not decision.halts


def test_requirement_traces_are_split_into_ids(real_plan):
    """Comma-separated traces ("APU-017, C-01, C-05") must flatten to individual ids so the
    coverage matrix keys on each requirement, not one mega-id."""
    plan, _ = real_plan
    s_p1 = next(s for s in plan["steps"] if s["step_id"] == "S-P1")
    traces = s_p1.get("traces_to") or s_p1.get("traces_requirements")
    assert "APU-017" in traces and "C-01" in traces and "C-05" in traces
    assert all("," not in t for t in traces)


def test_blocking_type_flag_alone_does_not_halt_a_pass():
    """Unit guard: gate=BLOCKING + verdict=PASS (no real defects) -> PROCEED."""
    plan = {"gate_status": {"verdict": "PASS", "gate": "BLOCKING"}, "steps": [],
            "blocking_defects": [], "structural_faults": []}
    assert evaluate_gate(plan).decision == "PROCEED"


def test_real_fail_still_halts():
    """Guard against masking a genuine block: verdict FAIL or a real blocking_defect halts."""
    assert evaluate_gate({"gate_status": {"verdict": "FAIL", "gate": "BLOCKING"},
                          "steps": []}).decision == "HALT"
    assert evaluate_gate({"gate_status": {"verdict": "PASS", "gate": "OPEN"},
                          "blocking_defects": [{"id": "D1", "type": "x"}],
                          "steps": []}).decision == "HALT"
