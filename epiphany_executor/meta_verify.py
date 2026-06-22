"""Meta-verification helper (wiring-check Phase 1): proves the closure gate ENFORCES —
a red contract drives the executor's coverage->terminal to closure-blocked (done
unreachable), green reaches done. Guarded so a missing wiring package never crashes import.
"""
from __future__ import annotations

from pathlib import Path

from .closure_gate import coverage_closure_with_gate

try:
    from goatcs_harness.wiring.executor_gate import CLOSURE_BLOCKED
except Exception:                                  # pragma: no cover
    CLOSURE_BLOCKED = "closure-blocked"


def drive_executor_to_terminal(plan: dict, skill_pkg: str | Path, *,
                               plan_path: str | Path | None = None,
                               base_coverage: dict | None = None) -> dict:
    base = dict(base_coverage or {"requirements": "covered"})
    closure = coverage_closure_with_gate(plan, skill_pkg, base, plan_path=plan_path)
    if closure["route"] == CLOSURE_BLOCKED:
        return {"terminal": CLOSURE_BLOCKED, "reached_done": False, "halted": True,
                "gaps": closure["wiring_closure"].get("gaps", []), "coverage": closure}
    return {"terminal": "done", "reached_done": True, "halted": False, "coverage": closure}
