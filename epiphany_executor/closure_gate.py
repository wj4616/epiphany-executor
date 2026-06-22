"""Executor closure-gate integration (wiring-check Phase 1) — the executor's closure layer.

Wires the deterministic ``goatcs-harness wiring-check`` gate into the executor's
``coverage_and_report`` → ``done`` closure. For a **harness-skill build** plan, the run may
declare ``done`` ONLY when the wiring-check exits 0; a non-zero exit yields a
``closure-blocked`` verdict carrying the gap-list — a recovery item routed back into the
build loop, exactly like a failed DoD, never a silent pass. This is the anti-false-green
enforcement (born from the epiphany-report-v3 half-wired ship).

The gate is a deterministic SUBPROCESS (``goatcs_harness.wiring.executor_gate``) whose exit
code IS the gate. When the plan carries no authored ``wiring_contract`` it falls back to the
BOOTSTRAPPED contract (``--plan``) — never a vacuous green.

DEPLOY NOTE: the wiring package ships in goatcs-harness. The import below is GUARDED so that
if the wiring-check tool is not on the path (e.g. a goatcs-harness checkout without it), the
gate degrades to an explicit advisory (``available: False``) rather than crashing the
executor. The full un-fakeable in-graph gate node is a reviewed follow-on hardening.
"""
from __future__ import annotations

import json
from pathlib import Path

try:                                                # guarded: never crash the executor
    from goatcs_harness.wiring.executor_gate import CLOSURE_BLOCKED, gate_coverage_to_done
    _WIRING_AVAILABLE = True
except Exception as _e:                             # pragma: no cover - environment-dependent
    CLOSURE_BLOCKED = "closure-blocked"
    _WIRING_AVAILABLE = False
    _IMPORT_ERROR = str(_e)

_HARNESS_SKILL_SIGNALS = ("wiring_contract", "skill_pkg", "tool_call", "graph.json", "GraphBuilder")


def is_harness_skill_build(plan: dict) -> bool:
    """True when the plan builds a goatcs-harness skill (so the closure gate applies)."""
    # epiphany-plan emits `target_profile` at the TOP LEVEL (e.g. "harness_skill"); older/nested
    # plans put it under `plan_meta`. Check BOTH — reading only plan_meta silently no-ops the
    # anti-false-green closure gate for the real plan shape (the finance-v2 false-green class).
    profile = plan.get("target_profile") or (plan.get("plan_meta") or {}).get("target_profile", "")
    if "harness" in str(profile).lower():
        return True
    if plan.get("wiring_contract"):
        return True
    for s in plan.get("steps", []):
        if str(s.get("target_subsystem", "")).lower() in ("harness", "skill"):
            blob = json.dumps(s)
            if any(sig in blob for sig in _HARNESS_SKILL_SIGNALS):
                return True
    return False


def _write_temp_contract(contract_rows, scratch: Path) -> Path:
    scratch.mkdir(parents=True, exist_ok=True)
    cf = scratch / "authored_wiring_contract.json"
    cf.write_text(json.dumps({"wiring_contract": contract_rows}))
    return cf


def enforce_closure(plan: dict, skill_pkg: str | Path, *, plan_path: str | Path | None = None,
                    scratch_dir: str | Path | None = None) -> dict:
    """The executor's coverage→done gate decision.

    ``{"route": "done", ...}`` only when the wiring-check is green; otherwise a
    ``closure-blocked`` halt-state dict with the gap-list. A non-harness-skill plan is N/A
    (route=done). If the wiring tool is unavailable, returns route=done with
    ``available: False`` (advisory) so the executor is never bricked.
    """
    if not is_harness_skill_build(plan):
        return {"route": "done", "gate": {"applicable": False,
                "note": "not a harness-skill build — closure gate N/A"}}
    if not _WIRING_AVAILABLE:
        return {"route": "done", "gate": {"applicable": True, "available": False,
                "warning": "goatcs-harness wiring-check not importable; closure gate SKIPPED "
                           f"(advisory). Install/checkout the wiring package. ({_IMPORT_ERROR})"}}

    import tempfile
    scratch = Path(scratch_dir or tempfile.mkdtemp(prefix="closure-gate-"))
    authored = plan.get("wiring_contract")
    if authored:
        contract_file = _write_temp_contract(authored, scratch)
        return gate_coverage_to_done(skill_pkg, contract=contract_file)
    # AUTHORED-IN-PACKAGE discovery: a real build ships its wiring_contract IN THE SKILL DIR
    # (skill_pkg/wiring-contract.{yaml,yml,json}), not inlined in the plan. Prefer it over the
    # bootstrapped fallback — else a legitimately-GREEN skill is BLOCKED by the auto-contract, which
    # over-strictly treats every wrapper CLI-helper module as an unwired node_body (the finance-v2
    # false-block class). The bootstrapped fallback stays as the last resort (never vacuous green).
    pkg = Path(skill_pkg)
    for fn in ("wiring-contract.yaml", "wiring-contract.yml", "wiring-contract.json",
               "wiring_contract.yaml", "wiring_contract.json"):
        cand = pkg / fn
        if cand.exists():
            return gate_coverage_to_done(skill_pkg, contract=cand)
    if plan_path:                                   # bootstrapped fallback (never vacuous)
        return gate_coverage_to_done(skill_pkg, plan=plan_path)
    return {
        "route": CLOSURE_BLOCKED, "halt_state": CLOSURE_BLOCKED,
        "reason": "harness-skill build with no authored wiring_contract and no plan_path to "
                  "bootstrap from — gate stays RED (never vacuous green)",
        "gaps": ["provide plan.wiring_contract or a plan_path for the bootstrapped fallback"],
    }


def _plan_harness_ledger(plan: dict) -> tuple[dict, set]:
    """Extract (facet->status, waived_set) from a plan's harness_ledger (S8 / WC-10 / APU-012).

    The ledger travels at top-level ``harness_ledger`` or under
    ``plan_meta.harness_forge.harness_ledger``. Generic plans carry none, so the
    facet closure tie is a no-op (INV-1)."""
    raw = plan.get("harness_ledger")
    if raw is None:
        raw = ((plan.get("plan_meta") or {}).get("harness_forge") or {}).get("harness_ledger")
    if not isinstance(raw, dict):
        return {}, set()
    ledger, waived = {}, set()
    for facet, rec in raw.items():
        if isinstance(rec, dict):
            status = str(rec.get("status", "")).lower()
            if rec.get("waiver_reason") or status == "waived":
                waived.add(facet)
            ledger[facet] = status or "missing"
        else:
            ledger[facet] = str(rec).lower()
            if str(rec).lower() == "waived":
                waived.add(facet)
    return ledger, waived


def facet_closure_report(plan: dict, skill_pkg: str | Path) -> dict:
    """Tie the harness_ledger to the built skill (WC-10 / APU-012).

    Returns a per-facet closure report: each facet is ``satisfied`` (the built skill
    carries evidence of it), ``waived`` (audited, exempt — surfaced WITH its reason),
    or ``missing`` (a present-but-empty facet reaching the executor -> BLOCK, the
    kill-criterion-(c) class). A facet is "satisfied" when the skill package or the
    plan's wiring contract references it. Returns ``{"applicable": False}`` for a
    generic/non-harness plan so byte-identity holds (INV-1)."""
    ledger, waived = _plan_harness_ledger(plan)
    if not ledger:
        return {"applicable": False, "facets": {}, "missing": [], "waived": []}

    # Evidence corpus: the skill package text + the plan's wiring contract / steps blob.
    corpus = json.dumps(plan.get("wiring_contract") or []) + json.dumps(plan.get("steps") or [])
    pkg = Path(skill_pkg)
    if pkg.exists():
        try:
            for p in pkg.rglob("*"):
                if p.is_file() and p.suffix in (".py", ".md", ".json", ".yaml", ".yml"):
                    corpus += "\n" + p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    facets: dict[str, dict] = {}
    missing: list[str] = []
    for facet, status in ledger.items():
        rec = (plan.get("harness_ledger") or {}).get(facet) or {}
        reason = rec.get("waiver_reason") if isinstance(rec, dict) else None
        if facet in waived or status == "waived":
            facets[facet] = {"verdict": "waived", "reason": reason or "(no reason recorded)"}
            continue
        # A facet is satisfied when its status claims present (full|thin) AND the built
        # skill actually references the facet (an explicit `facet:X` marker, or the facet
        # token in the package/contract). A "full"-claimed facet that the build never
        # mentions is treated as missing — the anti-false-green tie (kill-criterion (c)).
        satisfied = status in ("full", "thin") and (f"facet:{facet}" in corpus or facet in corpus)
        if satisfied:
            facets[facet] = {"verdict": "satisfied", "status": status}
        else:
            facets[facet] = {"verdict": "missing", "status": status}
            missing.append(facet)
    return {
        "applicable": True,
        "facets": facets,
        "missing": sorted(missing),
        "waived": sorted(waived),
    }


def coverage_closure_with_gate(plan: dict, skill_pkg: str | Path, base_coverage: dict, *,
                               plan_path: str | Path | None = None) -> dict:
    """Augment the executor's coverage_closure with the wiring-closure verdict AND the
    harness_ledger facet closure tie (S8). The run reaches ``done`` only if requirement
    coverage AND wiring-closure AND facet-closure are green. A present-but-empty (missing)
    facet BLOCKS — the kill-criterion-(c) anti-false-green tie."""
    decision = enforce_closure(plan, skill_pkg, plan_path=plan_path)
    out = dict(base_coverage)
    out["wiring_closure"] = decision

    facet_report = facet_closure_report(plan, skill_pkg)
    out["facet_closure"] = facet_report
    facet_blocked = bool(facet_report.get("applicable") and facet_report.get("missing"))

    blocked = decision["route"] == CLOSURE_BLOCKED or facet_blocked
    out["route"] = CLOSURE_BLOCKED if blocked else decision["route"]
    out["closure_blocked"] = blocked
    if facet_blocked:
        out["facet_gaps"] = [f"harness facet present-but-empty in build: {f}"
                             for f in facet_report["missing"]]
    return out
