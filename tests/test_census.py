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


# --- S9 / INV-4: the integrated-pipeline travelling fields (wiring_contract / wiring_rows /
# harness_ledger / waived_facets) must each have a consumer entry, or census BLOCKs by design.
# The authority is harness-forge-pipeline-integration.md rule #4 (F8). -------------------------

REAL_PIPELINE_PLAN = pathlib.Path(
    "/home/myuser/docs/solution/2026-06-14-pipeline-integration/02-plan/plan.json")


def test_real_harness_plan_passes(corpus):
    """The real integrated-pipeline plan carries top-level `wiring_contract` and per-step
    `wiring_rows`; merged into the design-intended multi-plan corpus, census must PASS — no
    `BLOCK-unconsumed` for those fields (F5). The multi-plan corpus supplies the other CONSUMED
    keys so stale-binding does not spuriously fire (census is designed to run over a corpus)."""
    corpus["real"] = json.loads(REAL_PIPELINE_PLAN.read_text())
    rep = census(corpus)
    blocked = [(f.scope, f.key) for f in rep.blocking]
    assert rep.passed, f"unexpected census blocks on the real harness plan: {blocked}"
    # and specifically the two F5 fields are bound to a consumer, not BLOCK-unconsumed. They are
    # harness-only (absent on a generic plan) so the consumer is `schema-tolerant:` (present-and-
    # consumed here, legitimately-absent elsewhere) — a non-blocking verdict, never a dead signal.
    by_key = {(f.scope, f.key): f for f in rep.findings}
    assert by_key[("plan", "wiring_contract")].verdict == "SCHEMA-TOLERANT"
    assert by_key[("step", "wiring_rows")].verdict == "SCHEMA-TOLERANT"
    assert not by_key[("plan", "wiring_contract")].verdict.startswith("BLOCK")
    assert not by_key[("step", "wiring_rows")].verdict.startswith("BLOCK")


def test_harness_ledger_and_waived_facets_consumed(corpus):
    """When Tasks A/C promote `harness_ledger` + `waived_facets` to plan top-level, census must
    bind them to the closure consumer (S-P5-closure), not BLOCK them as dead signals (INV-4)."""
    corpus["real"] = json.loads(REAL_PIPELINE_PLAN.read_text())
    corpus["real"]["harness_ledger"] = {"G": {"facet": "G", "status": "full"}}
    corpus["real"]["waived_facets"] = ["O"]
    rep = census(corpus)
    assert rep.passed, f"harness_ledger/waived_facets blocked: {[(f.scope, f.key) for f in rep.blocking]}"
    by_key = {(f.scope, f.key): f for f in rep.findings}
    # harness-only fields -> schema-tolerant consumer (non-blocking), tied to S-P5-closure.
    assert by_key[("plan", "harness_ledger")].verdict == "SCHEMA-TOLERANT"
    assert by_key[("plan", "waived_facets")].verdict == "SCHEMA-TOLERANT"
    assert "S-P5-closure" in by_key[("plan", "harness_ledger")].consumer


def test_unconsumed_promoted_field_blocks(corpus):
    """INV-4 teeth (R-7): a genuinely-dead promoted field with NO consumer STILL BLOCKs. Proves
    the Task-D fix maps only the real consumers — it does not degrade into blanket-allow."""
    corpus["real"] = json.loads(REAL_PIPELINE_PLAN.read_text())
    corpus["real"]["harness_orphan_field"] = {"dead": True}
    rep = census(corpus)
    assert not rep.passed
    orphan = [f for f in rep.blocking if f.key == "harness_orphan_field"]
    assert orphan and orphan[0].verdict == "BLOCK-unconsumed" and orphan[0].consumer is None
