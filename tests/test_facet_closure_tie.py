"""S8 / WC-10 / APU-012: executor closure_gate tied to the harness_ledger.

A present-but-empty (missing) facet reaching the executor BLOCKS (kill-criterion (c));
a waived facet is surfaced with its reason and exempt; a generic plan is N/A (INV-1).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, PKG)
from epiphany_executor import closure_gate as cg  # noqa: E402


def _skill_pkg(tmp_path, facet_markers):
    """A fake built skill dir whose code references the given facets via `facet:X` markers."""
    d = tmp_path / "built_skill"
    d.mkdir()
    (d / "graph.json").write_text('{"skill_name": "x"}')
    (d / "impl.py").write_text("# build markers\n" + "\n".join(f"# facet:{f}" for f in facet_markers))
    return str(d)


def _plan(ledger):
    return {"plan_meta": {"target_profile": "harness-forge"},
            "harness_ledger": ledger, "wiring_contract": [], "steps": []}


# --- facet_closure_report unit (the S8 tie itself, isolated from the wiring-check) ---

def test_report_missing_facet(tmp_path):
    pkg = _skill_pkg(tmp_path, ["G", "W"])  # build mentions only G, W
    plan = _plan({"G": "full", "W": "full", "V": "full"})  # V claimed full but never built
    rep = cg.facet_closure_report(plan, pkg)
    assert rep["applicable"] is True
    assert rep["missing"] == ["V"]
    assert rep["facets"]["G"]["verdict"] == "satisfied"


def test_report_all_satisfied(tmp_path):
    facets = ["G", "W", "V", "M", "B", "E", "O", "K"]
    pkg = _skill_pkg(tmp_path, facets)
    rep = cg.facet_closure_report(_plan({f: "full" for f in facets}), pkg)
    assert rep["missing"] == []


def test_report_waived_facet_surfaced_with_reason(tmp_path):
    facets = ["G", "W", "V", "M", "B", "E", "K"]
    pkg = _skill_pkg(tmp_path, facets)  # O not built
    ledger = {f: "full" for f in facets}
    ledger["O"] = {"status": "waived", "waiver_reason": "observability deferred to v2"}
    rep = cg.facet_closure_report(_plan(ledger), pkg)
    assert rep["missing"] == []  # O is waived, exempt
    assert rep["facets"]["O"]["verdict"] == "waived"
    assert "deferred" in rep["facets"]["O"]["reason"]


def test_report_generic_plan_na(tmp_path):
    pkg = _skill_pkg(tmp_path, [])
    rep = cg.facet_closure_report({"plan_meta": {"target_profile": "generic"}, "steps": []}, pkg)
    assert rep["applicable"] is False


# --- integration: a missing facet must BLOCK the overall closure decision (WC-10) ---

def test_missing_facet_blocks_overall_closure(tmp_path):
    pkg = _skill_pkg(tmp_path, ["G", "W"])
    plan = _plan({"G": "full", "W": "full", "V": "full"})
    out = cg.coverage_closure_with_gate(plan, pkg, {"route": "done"})
    assert out["closure_blocked"] is True
    assert "V" in out["facet_closure"]["missing"]
    assert any("V" in g for g in out.get("facet_gaps", []))


def test_generic_plan_overall_closure_unaffected_by_facets(tmp_path):
    """INV-1: a generic plan's overall closure is never blocked by the facet tie."""
    pkg = _skill_pkg(tmp_path, [])
    plan = {"plan_meta": {"target_profile": "generic"}, "steps": []}
    out = cg.coverage_closure_with_gate(plan, pkg, {"route": "done"})
    assert out["facet_closure"]["applicable"] is False
    # generic -> not a harness-skill build -> wiring gate N/A (route=done), facet tie N/A
    assert out["closure_blocked"] is False
