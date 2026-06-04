"""End-to-end DATA-CONTRACT trace: a harness/forge context-pack survives spec → plan → executor.

The three stages are otherwise independent (spec/plan are LLM-module skills; only the executor is
Python), so this pins the *interface* the contract promises — that the same pack, emitted by
epiphany-spec's §17, validates as epiphany-plan's plan_meta, and is consumed (not BLOCKed) by the
executor. See ~/docs/epiphany/harness-forge-pipeline-integration.md.
"""
import json
import pathlib

import pytest

from epiphany_executor.context_builder import build_step_context, harness_forge_pack

_PLAN_SCHEMA = pathlib.Path("/home/myuser/.claude/skills/epiphany-plan/plan.schema.json")

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
