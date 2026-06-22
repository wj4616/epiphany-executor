"""Harness-loadable shim + the INLINE-RUN session scaffold (§4).

Two roles:
  1. ``build(session_dir)`` — the runtime harness builds the Burr app generically; this exposes the
     entry that loads THIS package's graph.json (the headless drive path).
  2. ``scaffold_session`` / ``close_session`` (+ a CLI) — the **inline operating contract** boundary
     hooks. Under ``--provider inline`` the driving agent emulates the graph methodology by hand, so
     these make the run AUDITABLE and force the REAL tested modules (``epiphany_executor.coverage`` +
     ``epiphany_executor.closure_gate``) to run at the start and end — instead of the agent
     re-deriving coverage/closure informally. See SKILL.md "Inline operating contract".
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def build(session_dir, *, seed=None):
    from goatcs_harness import loader
    from goatcs_harness.build import build_application
    from goatcs_harness.persist import SessionPaths, make_persister
    spec = loader.load(os.path.join(HERE, "graph.json"))
    paths = SessionPaths(os.path.abspath(session_dir)).ensure()
    persister = make_persister(paths.db)
    return build_application(spec, persister, app_id=os.path.basename(session_dir),
                             partition_key=spec.skill_name, seed=seed or {})


# --------------------------------------------------------------------------
# inline operating-contract scaffold
# --------------------------------------------------------------------------
def _load_plan(plan_path: str) -> dict:
    with open(plan_path, encoding="utf-8") as fh:
        return json.load(fh)


def _steps_of(plan: dict) -> list[dict]:
    return plan.get("steps") or plan.get("plan", {}).get("steps") or []


# --------------------------------------------------------------------------
# 03-build relocation (Task C / S2 / C-10). Additive + default-off (INV-1):
# only a plan that carries a resolved solution workspace relocates its session
# under <ws>/03-build/. A generic plan is byte-identical — the session stays
# EXACTLY where the caller passed it, and NO solution.json harness key is written.
# Q-C: this is an executor-LOCAL edit (the executor *chooses* its session dir via
# the vendored resolver); the goatcs-harness persist.SessionPaths is untouched.
# --------------------------------------------------------------------------
def _plan_solution_dir(plan: dict) -> str | None:
    """The upstream solution workspace this plan belongs to, if any. Travels at
    `plan_meta.solution_dir` (the chain field epiphany-plan now bakes). Generic
    plans carry none -> returns None -> no relocation (INV-1)."""
    pm = plan.get("plan_meta")
    if isinstance(pm, dict) and pm.get("solution_dir"):
        return str(pm["solution_dir"])
    if plan.get("solution_dir"):
        return str(plan["solution_dir"])
    return None


def _resolve_build_dir(plan: dict, session_dir: str) -> tuple[str, str | None]:
    """Return (effective_session_dir, workspace_or_None).

    When the plan resolves a solution workspace, the effective session dir becomes
    `<ws>/03-build/session` (Q-B (i): the session/scaffold dir only — the built-skill
    package stays operator-specified, NG-1). When it does not, the caller's
    `session_dir` is returned unchanged (INV-1 byte-identity)."""
    sd = _plan_solution_dir(plan)
    if not sd:
        return session_dir, None
    try:
        from epiphany_executor import solution_workspace as _sw
        ws = _sw.resolve(upstream=sd)
        return os.path.join(_sw.stage_subdir(ws, "build"), "session"), ws
    except Exception:                                   # resolver unavailable -> no relocation
        return session_dir, None


def scaffold_session(plan_path: str, session_dir: str, *, skill_pkg: str | None = None) -> dict:
    """Start-of-run boundary hook. Writes a structured per-step DoD checklist + runs the REAL
    coverage gate. Returns a summary; an executor-caused orphan or an empty-acceptance step is a
    HARD start-gate finding the agent must resolve (never a silent pass)."""
    from epiphany_executor import coverage as _coverage

    plan = _load_plan(plan_path)
    steps = _steps_of(plan)
    # 03-build relocation (additive; generic unchanged — INV-1). Keeps scaffold + close aligned so
    # the per-step checklist and the closure report live in the same 03-build/session for a harness run.
    eff_session, _workspace = _resolve_build_dir(plan, session_dir)
    sess = os.path.join(os.path.abspath(eff_session), ".executor-session")
    os.makedirs(sess, exist_ok=True)

    # per-step DoD checklist (acceptance + integration_checks + outputs, each with an evidence slot)
    empty_criteria: list[str] = []
    with open(os.path.join(sess, "steps.jsonl"), "w", encoding="utf-8") as fh:
        for s in steps:
            acc = s.get("acceptance_criteria") or []
            if not acc:
                empty_criteria.append(s.get("id", "?"))
            fh.write(json.dumps({
                "id": s.get("id"),
                "goal": s.get("goal"),
                "acceptance_criteria": acc,
                "integration_checks": s.get("integration_checks") or [],
                "outputs": s.get("outputs") or [],
                "dependencies": s.get("dependencies") or [],
                "traces_requirements": s.get("traces_requirements") or s.get("traces") or [],
                "dod_evidence": None,            # agent fills: concrete evidence per acceptance item
                "dod_verdict": "PENDING",        # agent sets: PASS | FAILED | BLOCKED (role-separated)
            }) + "\n")

    cov = _coverage.coverage_report(plan)
    cov_out = {
        "matrix_size": len(cov.matrix),
        "executor_caused_orphans": [o.requirement for o in cov.executor_caused],
        "plan_caused_orphans": [o.requirement for o in cov.plan_caused],
        "blocks": cov.blocks,
    }
    with open(os.path.join(sess, "coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(cov_out, fh, indent=1)

    return {
        "session": sess,
        "steps": len(steps),
        "empty_criteria_steps": empty_criteria,     # each => BLOCKED, not auto-pass (verify_dod gate)
        "coverage": cov_out,
        "start_gate": "BLOCKED" if (cov.blocks or empty_criteria) else "OK",
    }


def close_session(plan_path: str, session_dir: str, *, skill_pkg: str | None = None) -> dict:
    """End-of-run boundary hook. Runs the REAL closure gate (wiring-check, for a harness-skill build)
    + the coverage-with-closure report. route='done' only when both are green; otherwise
    'closure-blocked' with the gap-list — the anti-false-green teeth, run as CODE not by hand."""
    from epiphany_executor import closure_gate as _cg
    from epiphany_executor import coverage as _coverage

    plan = _load_plan(plan_path)
    # 03-build relocation (additive; generic plans unchanged — INV-1).
    eff_session, workspace = _resolve_build_dir(plan, session_dir)
    sess = os.path.join(os.path.abspath(eff_session), ".executor-session")
    os.makedirs(sess, exist_ok=True)

    pkg = skill_pkg or HERE
    gate = _cg.enforce_closure(plan, pkg, plan_path=plan_path)
    out: dict = {"closure": gate, "session": sess}
    if skill_pkg:
        out["coverage_with_closure"] = _coverage.coverage_report_with_closure(
            plan, skill_pkg, plan_path=plan_path)
    out["route"] = gate.get("route", "done")

    # S8 (Task E): persist the per-facet closure report so the closure file lists every facet as
    # satisfied / waived (WITH its reason) / missing (WC-10/11, INV-6, R-6). The CODE already
    # computes this (closure_gate.facet_closure_report); here we surface it in closure.json AND tie
    # a present-but-empty (missing) facet into the route — a missing facet BLOCKS the close
    # (kill-criterion (c) anti-false-green tie). Generic plans => applicable:False, no route change.
    facet_report = _cg.facet_closure_report(plan, pkg)
    out["facet_closure"] = facet_report
    if facet_report.get("applicable") and facet_report.get("missing"):
        out["route"] = _cg.CLOSURE_BLOCKED
        out["facet_gaps"] = [f"harness facet present-but-empty in build: {f}"
                             for f in facet_report["missing"]]
    with open(os.path.join(sess, "closure.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)

    # Manifest write-back: stages.build + harness_ledger facet verdicts — HARNESS ONLY, and only
    # when an upstream workspace resolved. A generic run (workspace is None) writes nothing (INV-1).
    if workspace and _cg.is_harness_skill_build(plan):
        try:
            from epiphany_executor import solution_workspace as _sw
            _sw.update_stage(workspace, "build", {
                "status": out["route"],
                "dir": sess,
                "closure": os.path.join(sess, "closure.json"),
                "completed_ts": datetime.now(timezone.utc).isoformat(),
            })
            facet_report = _cg.facet_closure_report(plan, pkg)
            if facet_report.get("applicable"):
                verdicts = {f: {"facet": f, "status": v.get("status") or v.get("verdict"),
                                "build_verdict": v.get("verdict")}
                            for f, v in facet_report.get("facets", {}).items()}
                if verdicts:
                    _sw.update_ledger(workspace, verdicts)
        except Exception:                               # never brick the close on a manifest hiccup
            pass
    return out


def prepare_drive(plan_path: str, out_dir: str) -> dict:
    """Write the seed FILE for an inline graph drive + return the exact, correct drive command.
    Eliminates the two footguns: `--seed` takes a JSON file (not key=value), and `--read-dir` must
    include the plan's directory (else read_plan's fs.read_text is sandboxed out → UNCERTAIN)."""
    plan_abs = os.path.abspath(plan_path)
    out = os.path.abspath(out_dir)
    # When the plan resolves a solution workspace, the scratch/session lives under 03-build/ so the
    # drive command's --scratch-dir matches where scaffold/close write (additive; generic unchanged).
    try:
        _eff, _ws = _resolve_build_dir(_load_plan(plan_abs), out)
        if _ws:
            out = os.path.abspath(os.path.dirname(_eff))   # the 03-build/ dir (parent of /session)
    except Exception:
        pass
    os.makedirs(out, exist_ok=True)
    seed = os.path.join(out, "seed.json")
    with open(seed, "w", encoding="utf-8") as fh:
        json.dump({"plan_path": plan_abs}, fh)
    plan_dir = os.path.dirname(plan_abs)
    graph = os.path.join(HERE, "graph.json")
    drive_cmd = (f"goatcs-harness run {graph} --seed {seed} --provider inline "
                 f"--read-dir {plan_dir} --scratch-dir {out}/session")
    return {"seed": seed, "plan_dir": plan_dir, "graph": graph, "session": f"{out}/session",
            "drive_cmd": drive_cmd}


def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="epiphany_executor.bootstrap",
                                 description="inline operating-contract boundary hooks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare", help="write the seed file + print the correct inline drive command")
    pr.add_argument("plan_path")
    pr.add_argument("--out", required=True)
    sc = sub.add_parser("scaffold", help="start-of-run: per-step DoD checklist + coverage gate")
    sc.add_argument("plan_path")
    sc.add_argument("--session", required=True)
    sc.add_argument("--skill-pkg", default=None)
    cl = sub.add_parser("close", help="end-of-run: real closure gate (anti-false-green)")
    cl.add_argument("plan_path")
    cl.add_argument("--session", required=True)
    cl.add_argument("--skill-pkg", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "prepare":
        res = prepare_drive(args.plan_path, args.out)
        print(json.dumps(res, indent=1))
        print("\n# drive the executor graph inline:\n" + res["drive_cmd"])
        return 0
    if args.cmd == "scaffold":
        res = scaffold_session(args.plan_path, args.session, skill_pkg=args.skill_pkg)
        print(json.dumps(res, indent=1))
        return 3 if res["start_gate"] == "BLOCKED" else 0
    res = close_session(args.plan_path, args.session, skill_pkg=args.skill_pkg)
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("route") == "done" else 3


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
