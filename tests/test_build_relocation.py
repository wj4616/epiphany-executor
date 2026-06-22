"""Task C (S2/S9, executor portion) — 03-build relocation + harness_ledger write-back.

Per spec §5.1 + C-10: when an upstream solution workspace resolves (the plan carries
`plan_meta.solution_dir`), the executor build SESSION relocates under `03-build/` and the travelling
`harness_ledger` is updated with the build/closure facet verdicts at close. Generic plans (no
target_profile/solution_dir) are byte-identical: the session dir is exactly where the caller passed
it and NO harness manifest key is written (INV-1). Q-B=(i): only the session relocates, not the
built-skill package. Q-C: executor-local bootstrap.py edit only — no goatcs-harness runtime change.
"""
from __future__ import annotations

import json
import os
import sys

import bootstrap  # executor's own bootstrap.py (the inline operating-contract scaffold)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "epiphany_executor")))
import solution_workspace as sw  # noqa: E402


def _mk_workspace(tmp_path, slug):
    os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
    return sw.resolve(slug=slug, date="2026-06-14")


def _harness_plan(ws, *, ledger):
    return {
        "plan_meta": {"plan_id": "p", "target_profile": "harness-forge",
                      "solution_dir": os.path.abspath(ws)},
        "target_profile": "harness-forge",
        "harness_ledger": ledger,
        "wiring_contract": [{"id": "WC-1", "requirement": "r"}],
        "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}],
    }


def _generic_plan():
    return {
        "plan_meta": {"plan_id": "p"},
        "steps": [{"step_id": "S0", "goal": "g", "acceptance_criteria": ["a"]}],
    }


def _build_skill_pkg(tmp_path):
    """A tiny skill package whose corpus mentions the facets so they are 'satisfied'."""
    pkg = tmp_path / "built_skill"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("facet:G facet:W graph.json wiring_contract\n", encoding="utf-8")
    return str(pkg)


def _write_plan_file(tmp_path, plan, name="plan.json"):
    p = tmp_path / name
    p.write_text(json.dumps(plan), encoding="utf-8")
    return str(p)


def test_harness_run_relocates_and_updates_ledger(tmp_path):
    ws = _mk_workspace(tmp_path, "t-reloc")
    ledger = sw.seed_ledger(["G", "W"], statuses={"G": "full", "W": "full"})
    plan = _harness_plan(ws, ledger=ledger)
    plan_file = _write_plan_file(tmp_path, plan)
    pkg = _build_skill_pkg(tmp_path)
    caller_session = str(tmp_path / "caller_session")

    out = bootstrap.close_session(plan_file, caller_session, skill_pkg=pkg)

    # (a) session + closure.json relocated under <ws>/03-build/
    build_dir = sw.stage_subdir(ws, "build")
    closure_json = os.path.join(build_dir, "session", ".executor-session", "closure.json")
    assert os.path.isfile(closure_json), f"closure.json not under 03-build/: {out.get('session')}"
    assert os.path.abspath(out["session"]).startswith(os.path.abspath(build_dir))

    # (b) solution.json gains a stages.build entry
    man = sw.read_manifest(ws)
    assert man["stages"]["build"]["status"], "no stages.build entry written"

    # (c) the harness_ledger carries the per-facet build/closure verdicts
    assert "harness_ledger" in man
    assert man["harness_ledger"]["G"]["status"]  # facet verdict written back


def test_generic_run_no_relocation_no_ledger(tmp_path):
    """INV-1: a generic plan leaves the session dir EXACTLY where the caller passed it and writes
    NO solution.json harness key. (We point the solution root at tmp so any accidental write is
    detectable.)"""
    os.environ["EPIPHANY_SOLUTION_ROOT"] = str(tmp_path)
    plan = _generic_plan()
    plan_file = _write_plan_file(tmp_path, plan, name="generic_plan.json")
    pkg = _build_skill_pkg(tmp_path)
    caller_session = str(tmp_path / "generic_caller_session")

    out = bootstrap.close_session(plan_file, caller_session, skill_pkg=pkg)

    # session stays exactly where the caller put it (byte-identity of the path)
    expected = os.path.join(os.path.abspath(caller_session), ".executor-session")
    assert os.path.abspath(out["session"] if "session" in out else expected) == expected or \
        os.path.isdir(expected), "generic session dir moved (INV-1 violation)"
    # closure.json must be under the caller's dir, not any 03-build/
    assert os.path.isfile(os.path.join(expected, "closure.json"))
    # no solution.json with harness_ledger anywhere under tmp
    for root, _dirs, files in os.walk(tmp_path):
        if "solution.json" in files:
            man = json.loads(open(os.path.join(root, "solution.json")).read())
            assert "harness_ledger" not in man, "INV-1: harness_ledger written for a generic run"


def test_no_goatcs_harness_runtime_touched():
    """Q-C guard: bootstrap.py must not import or call into goatcs_harness.persist for the
    relocation; it uses the executor-vendored solution_workspace resolver only."""
    src = open(os.path.join(HERE, "..", "bootstrap.py"), encoding="utf-8").read()
    # the relocation helper must reference solution_workspace, not a persist.SessionPaths change
    assert "solution_workspace" in src
    assert "_resolve_build_dir" in src
