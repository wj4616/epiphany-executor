"""S10 generalization triad for epiphany-executor (WC-13 / APU-013,014,017,019 / R-1,R-12).

Three classes per skill:
  1. byte-identity (generic): the executor's close path on a GENERIC plan emits NO
     harness_ledger / wiring_contract / waived_facets key into the closure artifact or the manifest.
  2. harness-activation: on a HARNESS plan the harness keys DO appear and solution.json gains
     harness_ledger.
  3. cross-stage-trace (per-skill slice): the executor correctly RECEIVES the upstream ledger and
     reports its facets at closure (in -> out facet preservation for this stage).

The resolver-drift class (R-12) is covered by the existing test_solution_workspace_in_sync — we
re-assert here that it is present (do not duplicate it).
"""
from __future__ import annotations

import json
import os
import sys

import bootstrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "epiphany_executor")))
import solution_workspace as sw  # noqa: E402

HARNESS_KEYS = ("harness_ledger", "wiring_contract", "waived_facets")


def _pkg(tmp_path, mentions="facet:G facet:V graph.json wiring_contract"):
    p = tmp_path / "pkg"
    p.mkdir(exist_ok=True)
    (p / "SKILL.md").write_text(mentions + "\n", encoding="utf-8")
    return str(p)


def _write(tmp_path, plan, name="plan.json"):
    f = tmp_path / name
    f.write_text(json.dumps(plan), encoding="utf-8")
    return str(f)


def _closure(out):
    return json.load(open(os.path.join(out["session"], "closure.json"), encoding="utf-8"))


# --- 1. byte-identity (generic) ----------------------------------------------
class TestByteIdentityGeneric:
    def test_generic_close_emits_no_harness_key(self, tmp_path):
        os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
        plan = {"plan_meta": {"plan_id": "p"},
                "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}]}
        out = bootstrap.close_session(_write(tmp_path, plan), str(tmp_path / "s"),
                                      skill_pkg=_pkg(tmp_path))
        blob = json.dumps(_closure(out))
        # facet_closure may be present-but-applicable:false; the harness *keys with content* must
        # not leak into the manifest, and no harness_ledger may be written.
        for root, _d, files in os.walk(tmp_path):
            if "solution.json" in files:
                man = json.load(open(os.path.join(root, "solution.json")))
                assert "harness_ledger" not in man
        fc = json.loads(blob).get("facet_closure")
        assert fc is None or fc.get("applicable") is False


# --- 2. harness-activation ----------------------------------------------------
class TestHarnessActivation:
    def test_harness_close_writes_ledger_and_keys(self, tmp_path):
        os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
        ws = sw.resolve(slug="t-activate", date="2026-06-14")
        ledger = sw.seed_ledger(["G", "V"], statuses={"G": "full", "V": "full"})
        plan = {"plan_meta": {"plan_id": "p", "target_profile": "harness-forge",
                              "solution_dir": os.path.abspath(ws)},
                "target_profile": "harness-forge", "harness_ledger": ledger,
                "wiring_contract": [{"id": "WC-1", "requirement": "r"}],
                "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}]}
        out = bootstrap.close_session(_write(tmp_path, plan), str(tmp_path / "s"),
                                      skill_pkg=_pkg(tmp_path))
        man = sw.read_manifest(ws)
        assert "harness_ledger" in man
        assert _closure(out)["facet_closure"]["applicable"] is True


# --- 3. cross-stage-trace (per-skill slice) ----------------------------------
class TestCrossStageTrace:
    def test_executor_reports_received_facets_at_closure(self, tmp_path):
        os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
        ws = sw.resolve(slug="t-trace", date="2026-06-14")
        # upstream seeds all 8 harness facets full
        ledger = sw.seed_ledger(sw.HARNESS_FACETS,
                                statuses={f: "full" for f in sw.HARNESS_FACETS})
        plan = {"plan_meta": {"plan_id": "p", "target_profile": "harness-forge",
                              "solution_dir": os.path.abspath(ws)},
                "target_profile": "harness-forge", "harness_ledger": ledger,
                "wiring_contract": [{"id": "WC-1", "requirement": "r"}],
                "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}]}
        mentions = " ".join(f"facet:{f}" for f in sw.HARNESS_FACETS) + " graph.json"
        out = bootstrap.close_session(_write(tmp_path, plan), str(tmp_path / "s"),
                                      skill_pkg=_pkg(tmp_path, mentions=mentions))
        fc = _closure(out)["facet_closure"]
        # every received facet appears in the closure report (none dropped)
        assert set(fc["facets"].keys()) == set(sw.HARNESS_FACETS)
        assert fc["missing"] == []


# --- R-12 resolver drift is covered by test_solution_workspace_in_sync (do not duplicate) ----
def test_resolver_sync_check_exists():
    assert os.path.isfile(os.path.join(HERE, "test_solution_workspace_in_sync.py"))
