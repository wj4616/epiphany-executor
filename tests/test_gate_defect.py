"""Plan-declared gate/defect honoring (epiphany-executor S-P1-gate-defect, IC-P1g, INV-17)."""
from __future__ import annotations

import json
import pathlib

import pytest

from epiphany_executor.gate_defect import evaluate_gate

RUNS_DIR = pathlib.Path("/home/myuser/docs/goatcs-output/epiphany-plan-runs")
GOATCS_V3 = RUNS_DIR / "2026-05-31-goatcs-v3-build-plan/goatcs-v3-build-execution-plan.json"
ALL_RUNS = [
    GOATCS_V3,
    RUNS_DIR / "2026-05-31-gotscs-v1-build-plan/gotscs-v1-build-execution-plan.json",
    RUNS_DIR / "2026-05-31-power-flywheel-next-phase-plan/power-flywheel-F1-F3-execution-plan.json",
]


def test_goatcs_v3_halts_before_step_1():
    plan = json.loads(GOATCS_V3.read_text())
    d = evaluate_gate(plan)
    assert d.halts
    # the gate FAIL is the lead reason (the plan author flagged it un-ready, INV-17)
    assert any("verdict='FAIL'" in r for r in d.reasons)
    # DEFECT-1 is surfaced
    assert any("DEFECT-1" in r or "blocking_defect" in r for r in d.reasons)


@pytest.mark.parametrize("path", ALL_RUNS, ids=lambda p: p.parent.name)
def test_all_real_runs_halt(path):
    assert evaluate_gate(json.loads(path.read_text())).halts


def test_clean_plan_proceeds():
    clean = {"gate_status": {"verdict": "PASS", "gate": "OPEN"},
             "blocking_defects": [], "structural_faults": [],
             "steps": [{"step_id": "s1", "acceptance_criteria": ["ok"],
                        "integration_checks": {"id": "IC1", "assert": "x", "status": "OK"}}]}
    d = evaluate_gate(clean)
    assert d.decision == "PROCEED"
    assert d.reasons == []


def test_open_status_does_not_halt():
    # "OPEN (...)" is non-blocking (only a DEFECT-prefixed status blocks)
    plan = {"gate_status": {"verdict": "PASS", "gate": "OPEN"},
            "steps": [{"step_id": "s1", "integration_checks": {"id": "I", "status": "OPEN (non-blocking)"}}]}
    assert evaluate_gate(plan).decision == "PROCEED"


def test_step_level_blocking_defect_halts_even_with_clean_gate():
    plan = {"gate_status": {"verdict": "PASS", "gate": "OPEN"}, "blocking_defects": [],
            "steps": [{"step_id": "s9", "integration_checks": {"id": "I", "status": "DEFECT:partial_binding"}}]}
    d = evaluate_gate(plan)
    assert d.halts
    assert d.blocking_steps == ["s9"]


def test_colon_and_dash_defect_spellings_both_block():
    for status in ("DEFECT — missing tests; BLOCKING", "DEFECT:underspecified_dependency_output"):
        plan = {"gate_status": {"verdict": "PASS", "gate": "OPEN"},
                "steps": [{"step_id": "s", "integration_checks": {"id": "I", "status": status}}]}
        assert evaluate_gate(plan).halts, status
