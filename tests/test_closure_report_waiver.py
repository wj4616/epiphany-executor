"""Task E (S8 remaining) — the closure report file must list each harness facet
satisfied/waived/missing, and a WAIVED facet must surface WITH its recorded reason (WC-10/11,
INV-6, R-6). The closure_gate CODE already computes this (facet_closure_report returns waived +
per-facet reason); this wires it into the persisted closure.json via close_session.
"""
from __future__ import annotations

import json
import os
import sys

import bootstrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "epiphany_executor")))
import solution_workspace as sw  # noqa: E402


def _mk_workspace(tmp_path, slug):
    os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
    return sw.resolve(slug=slug, date="2026-06-14")


def _built_pkg(tmp_path, *, mentions="facet:G facet:V graph.json"):
    pkg = tmp_path / "built_skill"
    pkg.mkdir(exist_ok=True)
    (pkg / "SKILL.md").write_text(mentions + "\n", encoding="utf-8")
    return str(pkg)


def _plan_with_ledger(ws, ledger):
    return {
        "plan_meta": {"plan_id": "p", "target_profile": "harness-forge",
                      "solution_dir": os.path.abspath(ws)},
        "target_profile": "harness-forge",
        "harness_ledger": ledger,
        "wiring_contract": [{"id": "WC-1", "requirement": "r"}],
        "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}],
    }


def _write(tmp_path, plan, name="plan.json"):
    p = tmp_path / name
    p.write_text(json.dumps(plan), encoding="utf-8")
    return str(p)


def _load_closure(out):
    with open(os.path.join(out["session"], "closure.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_waived_facet_shown_with_reason(tmp_path):
    ws = _mk_workspace(tmp_path, "t-waiver")
    ledger = sw.seed_ledger(["G", "O"], statuses={"G": "full", "O": "waived"})
    ledger["O"]["waiver_reason"] = "deferred to v2 per operator"
    plan = _plan_with_ledger(ws, ledger)
    pkg = _built_pkg(tmp_path, mentions="facet:G graph.json")  # O is waived, not in corpus
    out = bootstrap.close_session(_write(tmp_path, plan), str(tmp_path / "s"), skill_pkg=pkg)

    closure = _load_closure(out)
    fc = closure.get("facet_closure")
    assert fc and fc.get("applicable"), "closure.json must carry facet_closure"
    assert fc["facets"]["O"]["verdict"] == "waived"
    assert "deferred to v2" in fc["facets"]["O"]["reason"]
    assert "O" in fc["waived"]


def test_missing_facet_blocks_closure(tmp_path):
    """R-6 teeth: a `full`-claimed facet absent from the built package corpus => the facet is
    `missing` and the close route is closure-blocked. Then waiving it lets the run proceed
    (audited override), proving both teeth and the override path."""
    ws = _mk_workspace(tmp_path, "t-missing")
    ledger = sw.seed_ledger(["G", "B"], statuses={"G": "full", "B": "full"})
    plan = _plan_with_ledger(ws, ledger)
    pkg = _built_pkg(tmp_path, mentions="facet:G graph.json")   # B is full-claimed but absent
    out = bootstrap.close_session(_write(tmp_path, plan), str(tmp_path / "s"), skill_pkg=pkg)
    closure = _load_closure(out)
    fc = closure["facet_closure"]
    assert "B" in fc["missing"], "a full-claimed-but-absent facet must be reported missing"
    assert closure.get("route") == "closure-blocked" or out.get("route") == "closure-blocked", \
        "a missing facet must block the close route (R-6 teeth)"

    # audited override: waive B -> it proceeds, with the reason recorded
    ledger["B"]["status"] = "waived"
    ledger["B"]["waiver_reason"] = "B intentionally out of scope this build"
    plan2 = _plan_with_ledger(ws, ledger)
    out2 = bootstrap.close_session(_write(tmp_path, plan2, name="plan2.json"),
                                   str(tmp_path / "s2"), skill_pkg=pkg)
    closure2 = _load_closure(out2)
    fc2 = closure2["facet_closure"]
    assert "B" not in fc2["missing"]
    assert fc2["facets"]["B"]["verdict"] == "waived"
    assert "out of scope" in fc2["facets"]["B"]["reason"]


def test_generic_plan_no_facet_closure(tmp_path):
    """INV-1: a generic plan's closure.json carries no applicable facet_closure (or applicable:False)."""
    os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
    plan = {"plan_meta": {"plan_id": "p"},
            "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}]}
    pkg = _built_pkg(tmp_path)
    out = bootstrap.close_session(_write(tmp_path, plan, name="gen.json"),
                                  str(tmp_path / "gs"), skill_pkg=pkg)
    closure = _load_closure(out)
    fc = closure.get("facet_closure")
    assert fc is None or fc.get("applicable") is False
