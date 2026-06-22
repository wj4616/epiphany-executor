"""End-to-end DATA-CONTRACT trace: a harness/forge context-pack survives spec → plan → executor.

The three stages are otherwise independent (spec/plan are LLM-module skills; only the executor is
Python), so this pins the *interface* the contract promises — that the same pack, emitted by
epiphany-spec's §17, validates as epiphany-plan's plan_meta, and is consumed (not BLOCKed) by the
executor. See ~/docs/epiphany/harness-forge-pipeline-integration.md.
"""
import json
import os
import pathlib
import sys

import pytest

from epiphany_executor.context_builder import build_step_context, harness_forge_pack

_HERE = pathlib.Path(__file__).resolve().parent
# Resolve plan.schema.json from the sibling epiphany-plan skill, wherever this skill is installed
# (staging copy, live ~/.claude/skills, or a worktree) — location-independent so the e2e trace
# always validates against the plan skill that ships alongside this executor.
_PLAN_SCHEMA = _HERE.parent.parent / "epiphany-plan" / "plan.schema.json"

sys.path.insert(0, str(_HERE.parent / "epiphany_executor"))
import solution_workspace as sw  # noqa: E402
from epiphany_executor import closure_gate as cg  # noqa: E402
import bootstrap  # noqa: E402

# (1) what epiphany-spec emits in the §17 Handoff Bundle as `harness_forge_context`
SPEC_PACK = {
    "target_profile": "harness-forge",
    "capability_gaps": [{"gap": "design IR ⊊ runtime IR", "criticality": "high", "evidence": "APU-03"}],
    "harness_primitives": ["fan-out/AND-join", "ensemble.quorum"],
    "grammar_cells": [{"cell": "RESEARCHER+subagent-fanout+AND-join", "oracle_kind": "differential"}],
    "correctness_basis": "differential",
    "machine_advantage": ["design candidate-gen multi-attempt+diverse"],
    "harness_first": True,
    "invariants": ["INV-1", "INV-MACHINE", "INV-HARNESS-FIRST"],
    "provider_hint": "codex",
    "self_modifying": True,
}


def _plan_from_pack(pack):
    """what epiphany-plan's emit writes when ingest set target_profile == harness-forge."""
    return {
        "plan_meta": {
            "plan_id": "fg", "schema": "epiphany-plan.plan_document.v1",
            "source_spec": "~/docs/solution/2026-06-03-forge-generalize/spec-final.md",
            "target_profile": "harness-forge", "harness_forge": pack,
        },
        "coverage_verdict": {"decision": "PASS"},
        "steps": [{
            "step_id": "S2", "goal": "close the design-IR↔runtime gap", "actions": ["edit design_ir.py"],
            "acceptance_criteria": ["gate: forge-subset-runtime green"],
            "target_subsystem": "generator/design_ir.py",
            "outputs": ["projects/goatcs-harness/goatcs_harness/generator/design_ir.py"],
        }],
        "execution_order": ["S2"],
    }


def test_pack_validates_as_plan_meta():
    """(2) the spec pack rides into epiphany-plan's plan_meta and validates against plan.schema.json."""
    jsonschema = pytest.importorskip("jsonschema")
    if not _PLAN_SCHEMA.exists():
        pytest.skip("plan.schema.json not present")
    schema = json.loads(_PLAN_SCHEMA.read_text())
    jsonschema.validate(_plan_from_pack(SPEC_PACK), schema)


def test_executor_consumes_pack_and_changes_behavior():
    """(3) the executor reads the same plan_meta: the pack steers the step context. (The no-BLOCK
    census property is proven over the real normalized corpus in test_harness_forge_integration.)"""
    plan = _plan_from_pack(SPEC_PACK)

    # consumption: the pack resolves and steers the step context (self-clobber → DEEP + provider hint)
    pm = plan["plan_meta"]
    assert harness_forge_pack(pm) == SPEC_PACK
    ctx = build_step_context({"S2": {"dod": {"acceptance_criteria": ["x"]}}}, "S2", {"S2": set()},
                             plan_meta=pm, step=plan["steps"][0])
    assert ctx.target_profile == "harness-forge"
    assert ctx.self_clobber_paths == plan["steps"][0]["outputs"]
    assert ctx.thinking_tier.value == "deep"
    assert any("codex" in line for line in ctx.harness_forge_context)


# ============================================================================
# S11 (Task G): the 8-facet harness_ledger survives brief -> spec -> plan -> executor closure.
# This is the NEW trace the spec requires (the block above is the v2 context-pack trace, retained).
# It drives the DATA CONTRACT across the three stages (not a live LLM run) and asserts SET EQUALITY
# of the 8 facet codes at brief-seed and at the executor closure report — nothing dropped (R-11).
# ============================================================================

# A spec body with content for every facet G..K (so the spec V14 carry-through accepts).
_FULL_SPEC = """# Spec
## Graph Architecture
node A, node B; topology declared in graph.json
## Wiring-Contract
| WC-1 | resolve | node_body | fired_marker |
## V-Battery / Acceptance
R-1 falsifiable; break_attempt holds
## Module Bodies
each node body / implementation is specified
## Capability Backlog
harness primitive: census consumer-entry; capability_gap noted
## Execution Contract
provider inline; worktree isolation; interface defined
## Observability & Replay
session checkpoint; replay from the ledger; telemetry
## Kill Criteria
abort/halt when budget red
"""

_ROW = {"id": "WC-1", "requirement": "resolve workspace", "mechanism": "node_body",
        "fired_marker": {"kind": "node_exec", "value": "dir exists"}, "traces": ["APU-1"]}
_RUNTIME_APU = {"id": "APU-1", "type": "functional", "text": "resolve workspace"}


_BRIEF_FIXTURE = _HERE / "fixtures" / "harness_brief_fixture.json"


def _brief_fixture(facets=None):
    """The minimal harness brief handoff seeding the 8 facets full (loaded from the on-disk
    fixture so the fixture is load-bearing). When `facets` is given, restrict to that subset."""
    data = json.loads(_BRIEF_FIXTURE.read_text())
    if facets is not None:
        data["harness_ledger"] = {f: data["harness_ledger"][f] for f in facets}
    return data


def _built_pkg(tmp_path, facets):
    pkg = tmp_path / "built_skill"
    pkg.mkdir(exist_ok=True)
    (pkg / "SKILL.md").write_text(
        " ".join(f"facet:{f}" for f in facets) + " graph.json wiring_contract\n", encoding="utf-8")
    return str(pkg)


def _spec_v14(tmp_path, ledger, *, drop_section=None):
    """Run the spec's REAL v14 carry-through over the arrived ledger."""
    spec_skill = _HERE.parent.parent / "epiphany-spec"
    sys.path.insert(0, str(spec_skill))
    import yaml
    from scripts.verifications.v14_wiring_contract import run as v14_run  # noqa
    spec_text = _FULL_SPEC
    if drop_section:
        spec_text = spec_text.replace(drop_section, "")
    sp = tmp_path / "spec.md"
    sp.write_text(spec_text)
    sd = tmp_path / "session.md"
    sd.write_text(yaml.safe_dump({"session_id": "x", "state": "RUNNING",
                                  "target_profile": "harness-forge", "apus": [_RUNTIME_APU],
                                  "wiring_contract_rows": [_ROW], "harness_ledger": ledger}))
    return v14_run(sp, sd)


def test_eight_facets_survive_to_closure(tmp_path, monkeypatch):
    monkeypatch.setenv("EPIPHANY_SOLUTION_ROOT", str(tmp_path))
    ws = sw.resolve(slug="e2e-trace", date="2026-06-14")

    # --- brief: seed the 8 facets ---
    brief = _brief_fixture()
    brief_facets = set(brief["harness_ledger"].keys())
    assert brief_facets == set(sw.HARNESS_FACETS)

    # --- spec: V14 carry-through accepts every arrived facet ---
    v14 = _spec_v14(tmp_path, brief["harness_ledger"])
    assert v14["status"] == "pass", v14["details"]

    # --- plan: finalize_workspace mirrors the ledger; census passes on the plan shape ---
    plan = {
        "plan_meta": {"plan_id": "p", "target_profile": "harness-forge",
                      "solution_dir": os.path.abspath(ws)},
        "target_profile": "harness-forge",
        "harness_ledger": brief["harness_ledger"],
        "wiring_contract": [_ROW],
        "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"],
                   "wiring_rows": ["WC-1"]}],
    }
    plan_file = tmp_path / "02-plan-plan.json"
    plan_file.write_text(json.dumps(plan))
    # census: the travelling fields are consumed, not BLOCKed (Task D)
    from epiphany_executor.census import census
    rep = census({"e2e": plan})
    block_unconsumed = [f for f in rep.blocking if f.verdict == "BLOCK-unconsumed"]
    assert not block_unconsumed, f"travelling fields blocked: {[f.key for f in block_unconsumed]}"

    # --- executor: close_session reports all 8 facets satisfied (none missing) ---
    pkg = _built_pkg(tmp_path, sw.HARNESS_FACETS)
    out = bootstrap.close_session(str(plan_file), str(tmp_path / "sess"), skill_pkg=pkg)
    fc = json.load(open(os.path.join(out["session"], "closure.json")))["facet_closure"]
    closure_facets = set(fc["facets"].keys())

    # SET EQUALITY: the 8 facet codes at brief-seed == at closure (R-11, nothing dropped)
    assert closure_facets == brief_facets == set(sw.HARNESS_FACETS)
    assert fc["missing"] == []
    # and the manifest carries the ledger after the (simulated) full run
    man = sw.read_manifest(ws)
    assert set(man["harness_ledger"].keys()) >= set(sw.HARNESS_FACETS)


def test_dropping_a_facet_fails_the_trace(tmp_path, monkeypatch):
    """R-11 teeth: drop facet O at the spec stage -> the trace FAILS (O is reported missing /
    absent at the closure facet set). Proves the trace has teeth, not theater."""
    monkeypatch.setenv("EPIPHANY_SOLUTION_ROOT", str(tmp_path))
    ws = sw.resolve(slug="e2e-drop", date="2026-06-14")

    brief = _brief_fixture()
    # spec stage drops the Observability (O) content -> V14 must FAIL (facet would be dropped)
    v14 = _spec_v14(tmp_path, brief["harness_ledger"],
                    drop_section="## Observability & Replay\nsession checkpoint; "
                                 "replay from the ledger; telemetry\n")
    assert v14["status"] == "fail", "dropping O should fail the spec carry-through (teeth)"

    # and at the executor: a build whose corpus omits O leaves O missing at closure
    plan = {
        "plan_meta": {"plan_id": "p", "target_profile": "harness-forge",
                      "solution_dir": os.path.abspath(ws)},
        "target_profile": "harness-forge",
        "harness_ledger": brief["harness_ledger"],
        "wiring_contract": [_ROW],
        "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}],
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    pkg = _built_pkg(tmp_path, [f for f in sw.HARNESS_FACETS if f != "O"])  # O omitted from build
    out = bootstrap.close_session(str(plan_file), str(tmp_path / "sess"), skill_pkg=pkg)
    fc = json.load(open(os.path.join(out["session"], "closure.json")))["facet_closure"]
    assert "O" in fc["missing"], "a facet dropped from the build must be reported missing (R-11)"


def test_schema_resolves_from_sibling_plan_skill():
    """plan.schema.json must resolve from the sibling epiphany-plan skill, wherever installed
    (location-independent: works in staging, live ~/.claude/skills, or a worktree)."""
    assert _PLAN_SCHEMA.exists()
    assert _PLAN_SCHEMA.parent.name == "epiphany-plan"
    assert _PLAN_SCHEMA.name == "plan.schema.json"
