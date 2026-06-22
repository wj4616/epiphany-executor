"""MD normalizers -> execution-plan dict, round-tripped through the harness importer
(epiphany-executor S-P1, tracker item (b))."""
from __future__ import annotations

import pathlib

import pytest

from epiphany_executor.md_normalizer import normalize_brainstorming_md, normalize_plan_md
from goatcs_harness.epiphany_plan_importer import build_graphspec

PLAN_DIR = pathlib.Path("/home/myuser/projects/epiphany-plan")
MD_PLANS = sorted(PLAN_DIR.glob("*.md"))


@pytest.mark.parametrize("path", MD_PLANS, ids=lambda p: p.name)
def test_reference_md_plans_normalize_and_import(path):
    plan, lossy = normalize_plan_md(path.read_text())
    assert plan["steps"], f"{path.name}: no steps parsed"
    # round-trip through the SINGLE harness ingest authority
    spec = build_graphspec(plan, "shamd")
    assert len(spec.real_node_ids) == len(plan["steps"])
    # the reference plans are well-structured -> no lossy degradation
    assert lossy == [], f"{path.name}: unexpected lossy fields {lossy}"


def test_md_dependencies_become_edges_with_edge_class():
    # the goatcs-v3 MD declares typed deps (kind/edge_class annotations) -> typed dep objects
    plan, _ = normalize_plan_md((PLAN_DIR / "goatcs-v3-build-execution-plan.md").read_text())
    typed = [d for s in plan["steps"] for d in s.get("dependencies", []) if isinstance(d, dict)]
    assert typed, "expected typed deps from the MD edge_class annotations"
    assert any(d.get("edge_class") == "implementation-prerequisite" for d in typed)
    spec = build_graphspec(plan, "shamd")
    assert any(e.kind == "required" for e in spec.edges)


def test_md_gate_status_maps_from_coverage_verdict():
    # goatcs-v3 MD says decision: FAIL / blocking: true
    plan, _ = normalize_plan_md((PLAN_DIR / "goatcs-v3-build-execution-plan.md").read_text())
    assert plan["gate_status"]["verdict"] == "FAIL"
    assert plan["gate_status"]["gate"] == "BLOCKING"


def test_brainstorming_md_is_lossy_and_gated():
    md = "# Idea Dump\n## Make it faster\nbody\n## Make it prettier\nbody2\n"
    plan, lossy = normalize_brainstorming_md(md)
    assert lossy, "brainstorming must record lossy_fields"
    assert plan["normalized_from"] == "brainstorming-markdown"
    # degraded source is gated BLOCKING so the executor halts rather than treating it authoritative
    assert plan["gate_status"]["gate"] == "BLOCKING"
    assert len(plan["steps"]) == 2
    # zero declared deps -> document-order build_order fallback
    assert plan["build_order"] and "Document order" in plan["build_order"][0]
    spec = build_graphspec(plan, "shabs")
    assert len(spec.real_node_ids) == 2


def test_brainstorming_steps_are_unverifiable_inv10():
    plan, _ = normalize_brainstorming_md("# X\n## Section A\ntext\n")
    assert plan["steps"][0]["acceptance_criteria"] == []  # -> executor BLOCKs at DoD (INV-10)


def test_non_plan_markdown_raises():
    with pytest.raises(ValueError):
        normalize_plan_md("# Just a doc\n\nno step blocks here\n")
