"""Field census (epiphany-executor S-P1-census, IC-P1c, INV-2, CV-05)."""
from __future__ import annotations

import json
import pathlib

import pytest

from epiphany_executor.census import census

RUNS_DIR = pathlib.Path("/home/myuser/docs/goatcs-output/epiphany-plan-runs")
REAL = {
    "goatcs-v3": RUNS_DIR / "2026-05-31-goatcs-v3-build-plan/goatcs-v3-build-execution-plan.json",
    "gotscs-v1": RUNS_DIR / "2026-05-31-gotscs-v1-build-plan/gotscs-v1-build-execution-plan.json",
    "power-flywheel": RUNS_DIR / "2026-05-31-power-flywheel-next-phase-plan/power-flywheel-F1-F3-execution-plan.json",
}


@pytest.fixture
def corpus():
    return {k: json.loads(v.read_text()) for k, v in REAL.items()}


def test_real_corpus_every_field_bound(corpus):
    rep = census(corpus)
    assert rep.passed, f"unconsumed/stale fields: {[(f.scope, f.key) for f in rep.blocking]}"
    # the power-flywheel-only extra keys must each be bound to a consumer (not dropped)
    keys = {f"{f.scope}:{f.key}" for f in rep.findings}
    for extra in ("step:emit_note", "step:gap_surfaced", "step:is_gap_marker", "step:resolved_bindings",
                  "plan:removed_artifact"):
        assert extra in keys, f"census missed corpus key {extra}"


def test_silently_dropped_plan_field_blocks(corpus):
    corpus["goatcs-v3"]["a_brand_new_plan_key"] = {"x": 1}
    rep = census(corpus)
    assert not rep.passed
    assert any(f.scope == "plan" and f.key == "a_brand_new_plan_key" for f in rep.blocking)


def test_silently_dropped_step_field_blocks(corpus):
    corpus["gotscs-v1"]["steps"][0]["a_brand_new_step_key"] = 7
    rep = census(corpus)
    assert not rep.passed
    assert any(f.scope == "step" and f.key == "a_brand_new_step_key" for f in rep.blocking)


def test_present_but_unconsumed_is_the_block_condition(corpus):
    # CV-05: behavior-sensitivity. An unknown key has NO consumer -> present-but-unconsumed -> BLOCK.
    corpus["goatcs-v3"]["steps"][0]["unconsumed_metadata"] = "hi"
    rep = census(corpus)
    blocked = [f for f in rep.blocking if f.key == "unconsumed_metadata"]
    assert blocked and blocked[0].consumer is None and blocked[0].verdict == "BLOCK-unconsumed"


def test_report_renders(corpus):
    rep = census(corpus)
    text = rep.render()
    assert "Field Census Report" in text
    assert "verdict: PASS" in text
