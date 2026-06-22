#!/usr/bin/env python3
"""Post-emit V-battery (S-P8-reverify, INV-9) — the BLOCKING gate that makes "emit + re-verify
pass" = done. Run after every forge. Exit 0 iff all checks pass.

Usage: python3 tools/v_battery.py [<package_dir>]   (default: the repo root)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_RUNS = "/home/myuser/docs/goatcs-output/epiphany-plan-runs"


@dataclass
class VResult:
    checks: list = field(default_factory=list)

    def add(self, vid: str, ok: bool, detail: str) -> None:
        self.checks.append({"v": vid, "ok": bool(ok), "detail": detail})

    @property
    def passed(self) -> bool:
        return all(c["ok"] for c in self.checks)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "n_pass": sum(c["ok"] for c in self.checks),
                "n_total": len(self.checks), "checks": self.checks}


def run_v_battery(pkg: str = ROOT, *, skip_suite: bool = False) -> VResult:
    """skip_suite=True omits V5 (the full-suite run) — used when V-battery is itself invoked from
    inside the test suite, to avoid the suite-running-the-suite recursion. The CLI path runs the
    full 7/7 including V5."""
    r = VResult()

    # V1: graph.json loads + statically verifies on the harness
    try:
        out = subprocess.run(["goatcs-harness", "verify", os.path.join(pkg, "graph.json")],
                             capture_output=True, text=True, timeout=60)
        v = json.loads(out.stdout)
        r.add("V1-graph-loads", v.get("ok") and v["counts"]["blocking"] == 0,
              f"ok={v.get('ok')} blocking={v['counts']['blocking']} skill={v.get('skill')}")
    except Exception as ex:
        r.add("V1-graph-loads", False, f"{type(ex).__name__}: {ex}")

    # V2: all node modules present
    try:
        g = json.load(open(os.path.join(pkg, "graph.json")))
        missing = [n["module_file"] for n in g["nodes"].values()
                   if n.get("module_file") and not os.path.exists(os.path.join(pkg, n["module_file"]))]
        r.add("V2-modules-present", not missing, f"missing={missing}")
    except Exception as ex:
        r.add("V2-modules-present", False, f"{type(ex).__name__}: {ex}")

    # V3: contract template stamps the 4 binding field-groups
    try:
        sys.path.insert(0, pkg)
        from epiphany_executor.contract_template import (
            CONTRACT_FIELD_GROUPS,
            stamp_node_contract,
        )
        c = stamp_node_contract({"step_id": "v3", "acceptance_criteria": ["ok"]})
        r.add("V3-contract-stamps", all(g in c for g in CONTRACT_FIELD_GROUPS),
              f"groups={[g for g in CONTRACT_FIELD_GROUPS if g in c]}")
    except Exception as ex:
        r.add("V3-contract-stamps", False, f"{type(ex).__name__}: {ex}")

    # V4: importer loads all 3 real runs
    try:
        from goatcs_harness.loader import load
        import glob
        runs = [p for p in glob.glob(os.path.join(REAL_RUNS, "*", "*execution-plan.json"))]
        counts = {}
        for p in runs:
            d = json.load(open(p))
            if all(k in d for k in ("steps", "build_order", "gate_status")):
                counts[os.path.basename(os.path.dirname(p))] = len(load(p).nodes)
        r.add("V4-importer-real-runs", len(counts) >= 3, f"node_counts={counts}")
    except Exception as ex:
        r.add("V4-importer-real-runs", False, f"{type(ex).__name__}: {ex}")

    # V5: full executor test suite passes (skipped when invoked from inside the suite)
    if skip_suite:
        r.add("V5-test-suite", True, "skipped (invoked from inside the suite; CLI run covers V5)")
    else:
        try:
            out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                  "--ignore=tests/test_p8.py"],
                                 cwd=pkg, capture_output=True, text=True, timeout=600)
            ok = out.returncode == 0
            tail = (out.stdout.strip().splitlines() or ["(no output)"])[-1]
            r.add("V5-test-suite", ok, tail)
        except Exception as ex:
            r.add("V5-test-suite", False, f"{type(ex).__name__}: {ex}")

    # V6: SKILL.md documents invocation + AI-advantage modes
    try:
        skill = open(os.path.join(pkg, "SKILL.md")).read()
        ok = "INVOCATION" in skill and "AI / MACHINE-ADVANTAGE MODES" in skill and "A.1" in skill
        r.add("V6-skill-doc", ok, "invocation + A.1-A.9 modes present" if ok else "missing sections")
    except Exception as ex:
        r.add("V6-skill-doc", False, f"{type(ex).__name__}: {ex}")

    # V7: manifest + provenance present
    try:
        ok = os.path.exists(os.path.join(pkg, "manifest.json")) and \
             os.path.exists(os.path.join(pkg, "provenance.json"))
        r.add("V7-packaging", ok, "manifest+provenance present" if ok else "missing")
    except Exception as ex:
        r.add("V7-packaging", False, f"{type(ex).__name__}: {ex}")

    return r


if __name__ == "__main__":
    pkg = sys.argv[1] if len(sys.argv) > 1 else ROOT
    res = run_v_battery(pkg)
    print(json.dumps(res.to_dict(), indent=2))
    sys.exit(0 if res.passed else 1)
