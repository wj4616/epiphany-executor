"""Plan-drift detection (S-P5-drift, F-09, IR-06).

At session start the importer hashes each step's CANONICALIZED content (whitespace-normalized)
plus a plan-level hash. Drift is re-checked on every resume/fork and before each step start.
Resolution (spec §5.6): drift on an UNSTARTED step → re-import that step; drift on an
IN_FLIGHT/VERIFIED/ACCEPTED step → HALT + explicit human reconciliation. Canonicalization
prevents whitespace false-positives.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum

from .lifecycle import LifecycleState

_WS = re.compile(r"\s+")


def _canonicalize(obj) -> str:
    """Stable, whitespace-insensitive canonical form: sorted-key JSON with all whitespace runs
    collapsed. A whitespace-only edit yields the SAME canonical string (no false drift)."""
    dumped = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _WS.sub(" ", dumped).strip()


def step_hash(step: dict) -> str:
    return hashlib.sha256(_canonicalize(step).encode("utf-8")).hexdigest()


def plan_hash(plan: dict) -> str:
    # plan-level hash over everything EXCEPT the per-step bodies (those are hashed per step)
    skel = {k: v for k, v in plan.items() if k != "steps"}
    return hashlib.sha256(_canonicalize(skel).encode("utf-8")).hexdigest()


def snapshot_hashes(plan: dict) -> dict:
    """Recorded at session start: {plan: <hash>, steps: {step_id: <hash>}}."""
    steps = {}
    for s in plan.get("steps", []):
        if isinstance(s, dict) and s.get("step_id"):
            steps[s["step_id"]] = step_hash(s)
    return {"plan": plan_hash(plan), "steps": steps}


class DriftResolution(str, Enum):
    NONE = "none"
    REIMPORT = "reimport"            # UNSTARTED step drifted -> safe to re-import
    HALT = "halt"                    # started step drifted -> human reconciliation


@dataclass
class DriftVerdict:
    resolution: DriftResolution
    drifted_steps: list[str] = field(default_factory=list)
    plan_drifted: bool = False
    halt_steps: list[str] = field(default_factory=list)   # started + drifted -> halt
    reason: str = ""


def check_drift(recorded: dict, current_plan: dict,
                lifecycle: dict[str, LifecycleState] | None = None) -> DriftVerdict:
    """Compare current plan against the recorded snapshot. A drifted step that is UNSTARTED is
    re-imported; a drifted step that is IN_FLIGHT/VERIFIED/ACCEPTED forces a HALT."""
    lifecycle = lifecycle or {}
    cur = snapshot_hashes(current_plan)
    plan_drifted = cur["plan"] != recorded.get("plan")
    drifted, halt = [], []
    rec_steps = recorded.get("steps", {})
    for sid, h in cur["steps"].items():
        if sid in rec_steps and rec_steps[sid] != h:
            drifted.append(sid)
            state = lifecycle.get(sid, LifecycleState.UNSTARTED)
            if state is not LifecycleState.UNSTARTED:
                halt.append(sid)
    if halt or plan_drifted:
        return DriftVerdict(DriftResolution.HALT, drifted, plan_drifted, halt,
                            reason="started step (or plan skeleton) drifted -> human reconciliation")
    if drifted:
        return DriftVerdict(DriftResolution.REIMPORT, drifted, plan_drifted, [],
                            reason="UNSTARTED step(s) drifted -> safe re-import")
    return DriftVerdict(DriftResolution.NONE)
