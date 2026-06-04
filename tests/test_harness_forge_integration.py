"""Harness/forge pipeline accommodation (additive, default-off) — executor side.

Pins the integration contract (~/docs/epiphany/harness-forge-pipeline-integration.md):
- the census no longer BLOCKs on the plan's harness/forge tags (the latent gap #3 fix),
- the new fields are HONESTLY consumed (they change context/tier/gating, not just retained),
- a generic plan is byte-for-byte unaffected.
"""
import json
import pathlib

import pytest

_MODULES = pathlib.Path(__file__).resolve().parents[1] / "modules"


# --- runtime-contract wiring: the .md node contracts must actually INVOKE the library (B2/B3) ---
# (presence-only library tests pass while the runtime pipe is severed — these pin the invocation)

def test_build_context_contract_invokes_harness_consumer():
    """B2: N-build_context.md must instruct calling build_step_context with the plan_meta/step so the
    harness/forge context + tier-raise actually fire at runtime — not live only in unit tests."""
    body = (_MODULES / "N-build_context.md").read_text()
    assert "target_profile" in body and "harness-forge" in body
    assert "build_step_context" in body or "harness_forge_context_lines" in body
    assert "self_clobber" in body or "detect_self_clobber" in body


def test_precommit_gate_contract_wires_self_clobber():
    """B3: the self-clobber guard must be a real needs_human trigger in the gate that runs at runtime."""
    body = (_MODULES / "N-precommit_gate.md").read_text()
    assert "self_clobber" in body or "self-clobber" in body
    assert "needs_human" in body and "self_modifying" in body

from epiphany_executor.census import census
from epiphany_executor.context_builder import (
    ThinkingTier,
    build_step_context,
    detect_self_clobber,
    harness_forge_context_lines,
    harness_forge_pack,
)

_RUNS = pathlib.Path("/home/myuser/docs/goatcs-output/epiphany-plan-runs")
_REAL = {
    "goatcs-v3": _RUNS / "2026-05-31-goatcs-v3-build-plan/goatcs-v3-build-execution-plan.json",
    "gotscs-v1": _RUNS / "2026-05-31-gotscs-v1-build-plan/gotscs-v1-build-execution-plan.json",
    "power-flywheel": _RUNS / "2026-05-31-power-flywheel-next-phase-plan/power-flywheel-F1-F3-execution-plan.json",
}


@pytest.fixture
def corpus():
    return {k: json.loads(v.read_text()) for k, v in _REAL.items()}


# --- census: the gap #3 fix (plans using the conventions must not trip INV-2 BLOCK) ---

def test_census_baseline_corpus_still_passes(corpus):
    """Adding the harness/forge bindings did not introduce a stale-binding BLOCK on the real
    (generic) corpus — the additive keys are schema-tolerant/metadata-only, so absent ⇒ no BLOCK."""
    rep = census(corpus)
    assert rep.passed, [(f.scope, f.key, f.verdict) for f in rep.blocking]


def test_census_does_not_block_on_harness_forge_tags(corpus):
    """Inject the harness/forge tags a real plan would now carry — the census must NOT BLOCK.
    This is the latent gap #3 fix: before the consumer entries, target_subsystem/target_profile/
    harness_forge would each be BLOCK-unconsumed."""
    corpus["goatcs-v3"]["target_profile"] = "harness-forge"
    corpus["goatcs-v3"]["harness_forge"] = {"provider_hint": "codex", "self_modifying": True}
    corpus["goatcs-v3"]["steps"][0]["target_subsystem"] = "generator/infer.py"
    corpus["goatcs-v3"]["steps"][0]["obligation_class"] = "capability-closure"
    rep = census(corpus)
    assert rep.passed, [(f.scope, f.key, f.verdict) for f in rep.blocking]
    seen = {(f.scope, f.key): f.verdict for f in rep.findings}
    assert seen[("plan", "target_profile")] != "BLOCK-unconsumed"
    assert seen[("plan", "harness_forge")] != "BLOCK-unconsumed"
    assert seen[("step", "target_subsystem")] != "BLOCK-unconsumed"
    assert seen[("step", "obligation_class")] != "BLOCK-unconsumed"


# --- honest consumption: the fields actually change behavior ---

def test_pack_is_none_for_generic():
    assert harness_forge_pack(None) is None
    assert harness_forge_pack({"target_profile": "generic"}) is None
    assert harness_forge_pack({"target_profile": "harness-forge", "harness_forge": {"a": 1}}) == {"a": 1}


def test_context_lines_surface_provider_and_exit_codes():
    lines = harness_forge_context_lines({"provider_hint": "codex", "harness_first": True,
                                         "harness_primitives": ["AND-join"]},
                                        {"target_subsystem": "ir.py"})
    blob = "\n".join(lines)
    assert "codex" in blob and "exit-7" in blob and "exit-11" in blob
    assert "harness-first" in blob and "AND-join" in blob and "ir.py" in blob


def test_self_clobber_only_when_self_modifying_and_live_dir():
    pack = {"self_modifying": True}
    assert detect_self_clobber({"outputs": [".claude/skills/epiphany-plan/graph.json"]}, pack)
    assert detect_self_clobber({"outputs": ["projects/goatcs-harness/goatcs_harness/ir.py"]}, pack)
    assert detect_self_clobber({"outputs": ["projects/epiphany-report/x.py"]}, pack)  # family prefix
    assert detect_self_clobber({"outputs": ["/tmp/out/foo.py"]}, pack) == []          # not a live dir
    assert detect_self_clobber({"outputs": [".claude/skills/x/graph.json"]}, {"self_modifying": False}) == []
    assert detect_self_clobber({"outputs": ["x"]}, None) == []                        # generic plan


def test_self_clobber_does_not_over_gate_safe_outdir():
    """M1 fix: path-PREFIX matching — a /tmp out-dir path that merely *contains* a live token is
    NOT a clobber; and an explicit out_dir under a live family prefix is exempt."""
    pack = {"self_modifying": True}
    # contains '.claude/skills/' and 'graph.json' as substrings but resolves outside the live root
    assert detect_self_clobber({"outputs": ["/tmp/out/.claude/skills/x/graph.json"]}, pack) == []
    # explicit safe out_dir exempts even a family-prefix path
    pack_od = {"self_modifying": True, "out_dir": "projects/epiphany-report-rebuild"}
    assert detect_self_clobber({"outputs": ["projects/epiphany-report-rebuild/graph.json"]}, pack_od) == []
    # but an in-place live write is still caught despite the out_dir being set elsewhere
    assert detect_self_clobber({"outputs": ["projects/goatcs-harness/ir.py"]}, pack_od)


def test_build_step_context_raises_tier_and_flags_self_clobber():
    contracts = {"S1": {"dod": {"acceptance_criteria": ["ok"]}}}
    dag = {"S1": set()}
    pm = {"target_profile": "harness-forge", "harness_forge": {"self_modifying": True, "provider_hint": "codex"}}
    step = {"step_id": "S1", "target_subsystem": "ir.py",
            "outputs": ["projects/goatcs-harness/goatcs_harness/ir.py"]}
    ctx = build_step_context(contracts, "S1", dag, plan_meta=pm, step=step)
    assert ctx.target_profile == "harness-forge"
    assert ctx.target_subsystem == "ir.py"
    assert ctx.self_clobber_paths == ["projects/goatcs-harness/goatcs_harness/ir.py"]
    assert ctx.thinking_tier == ThinkingTier.DEEP            # raised by the self-clobber guard
    assert any("codex" in line for line in ctx.harness_forge_context)


def test_build_step_context_generic_unchanged():
    """A generic plan (no plan_meta / no profile) gets none of the accommodation."""
    contracts = {"S1": {"dod": {"acceptance_criteria": ["ok"]}}}
    ctx = build_step_context(contracts, "S1", {"S1": set()})
    assert ctx.target_profile == "generic"
    assert ctx.harness_forge_context == [] and ctx.self_clobber_paths == []
    assert ctx.target_subsystem is None
