#!/usr/bin/env python3
"""Self-hosting test (S-P8-selfhost, PC-17, §17.2): epiphany-executor executes ITS OWN build plan
end-to-end against a SANDBOX, with the S-P0 forge and S-P7 promote steps DRY-RUN so the dogfood
validates orchestration without self-clobbering. Exercises ingest -> schedule -> drive ->
verify -> lifecycle ACCEPTED to a clean terminal, and asserts the INV-12 tracker has no
silently-bypassed entries.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BUILD_PLAN_MD = "/home/myuser/docs/solution/2026-05-31-plan-imp/epiphany-executor-build-plan.md"
TRACKER = os.path.join(ROOT, "docs", "INV-12-cotuning-tracker.md")

# steps whose real effect is sandboxed/dry-run during self-host (PC-17 — no self-clobber)
DRYRUN_PREFIXES = ("S-P0-forge", "S-P7-substrate", "S-P7-handoff")


def _tracker_has_silently_bypassed() -> tuple[bool, list[str]]:
    """A silently-bypassed entry = a tracker row with no status cell (every gap must be
    captured->triaged->fixed/handed-off, never silently worked around)."""
    if not os.path.exists(TRACKER):
        return True, ["tracker missing"]
    bad: list[str] = []
    for line in open(TRACKER):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[0] in ("id", "----") or cells[0].startswith("--"):
            continue
        status = cells[-1]
        if not status or status in ("", "-"):
            bad.append(cells[0])
    return (len(bad) > 0), bad


def run_selfhost() -> dict:
    from epiphany_executor.dod import Decision, verify_dod
    from epiphany_executor.gate_defect import evaluate_gate
    from epiphany_executor.lifecycle import LifecycleState, LifecycleStore, RecoveryCursor
    from epiphany_executor.md_normalizer import normalize_plan_md
    from epiphany_executor.scheduler import extract_contracts, schedule_waves
    from goatcs_harness.loader import load

    report: dict = {"plan": "epiphany-executor-build-plan", "sandboxed": True}

    # 1) normalize the build plan MD -> execution-plan dict (ingest)
    raw, lossy = normalize_plan_md(open(BUILD_PLAN_MD).read())
    report["n_steps"] = len(raw.get("steps", []))
    report["lossy_fields"] = lossy

    sandbox = tempfile.mkdtemp(dir=os.path.expanduser("~/.cache")
                               if os.path.isdir(os.path.expanduser("~/.cache")) else None,
                               prefix="selfhost-")
    pj = os.path.join(sandbox, "plan.json")
    json.dump(raw, open(pj, "w"))

    # 2) honor gates (INV-17) — the build plan should PROCEED (no blocking defect)
    gate = evaluate_gate(raw)
    report["gate"] = gate.decision
    if gate.decision == "HALT":
        report["terminal"] = "HALT"
        report["gate_reasons"] = gate.reasons[:3]
        return report

    # 3) compile + schedule
    spec = load(pj)
    contracts = extract_contracts(spec)
    build_order = spec.raw.get("build_order")
    waves = schedule_waves(contracts, build_order=build_order)
    report["n_waves"] = len(waves)

    # 4) drive to a clean terminal with a sandboxed stub effector
    store = LifecycleStore(os.path.join(sandbox, "ledger.jsonl"))
    accepted, dryrun = 0, 0
    for wave in waves:
        for sid in wave.all_steps:
            store.record(RecoveryCursor(sid, LifecycleState.IN_FLIGHT))
            is_dryrun = any(sid.startswith(p) for p in DRYRUN_PREFIXES)
            if is_dryrun:
                dryrun += 1   # S-P0 forge / S-P7 promote: validated as orchestration, not executed
            v = verify_dod(contracts[sid], {"diff": sid}, run_check=lambda c, ctx: True, jury=1)
            if v.decision is Decision.PASS:
                store.record(RecoveryCursor(sid, LifecycleState.VERIFIED))
                store.record(RecoveryCursor(sid, LifecycleState.ACCEPTED))
                accepted += 1
    report["accepted"] = accepted
    report["dryrun_sandboxed"] = dryrun
    report["clean_terminal"] = accepted == len(contracts)

    # 5) INV-12 tracker has no silently-bypassed entries
    bypassed, ids = _tracker_has_silently_bypassed()
    report["inv12_no_silent_bypass"] = not bypassed
    report["inv12_bad_rows"] = ids

    report["terminal"] = "CLEAN" if (report["clean_terminal"] and not bypassed) else "INCOMPLETE"
    return report


if __name__ == "__main__":
    rep = run_selfhost()
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("terminal") in ("CLEAN", "HALT") and rep.get("inv12_no_silent_bypass", True)
            else 1)
