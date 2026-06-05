"""S4 / T4 — epiphany-executor convergence closure gate (APU-S4-EXECUTOR-CLOSURE).

The per-target closure predicate the dual bar (a) reads: a re-authored target is CLOSED only when its
OWN original test suite PASSES ∧ a session run reaches PASS ∧ the MEASURED ``forge_authored_pct``
meets the floor. All three conjuncts are required — any one false leaves the target NOT closed (F-A1).

This mirrors epiphany-report's ``convergence.py`` DISPOSITION-FLIP pattern (the deferred→ready
transition) but defines its OWN verdict fields: epiphany-report's ``ConvergenceVerdict`` carries
``forge_pct``/``battery_green``/``recalibrated`` but NOT the suite/session conjuncts F-A1 falsifies
on, so those fields are deliberately NOT mirrored. epiphany-executor had no convergence gate before.

The LIVE exercise is bar (a)/T6 (re-author epiphany-report + epiphany-executor, run each target's
real suite + a session, read the measured pct, write the closure record). Here the gate + its
recording land unit-tested against a stub target. INV-1: every conjunct is MEASURED from the recorded
run, never assumed — a missing/partial record reads as NOT closed (deferred), never closed by default.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

DEFAULT_FLOOR = 0.90
CLOSURE_RECORD = "forge_closure.json"            # measurements written by the bar-(a)/T6 re-author run
VERDICT_RECORD = "forge_closure_verdict.json"    # the recorded closure verdict


@dataclass
class ClosureVerdict:
    """The per-target convergence closure verdict. ``floor_met``/``closed``/``disposition`` are
    DERIVED — only the three measured signals + the floor are stored."""

    original_suite_pass: bool
    session_pass: bool
    forge_authored_pct: float
    floor: float = DEFAULT_FLOOR

    @property
    def floor_met(self) -> bool:
        # ≥ : pct == floor counts as met. A pct outside [0, 1] is a nonsensical measurement (a fraction
        # by construction) — fail-closed rather than let a buggy >1.0 pct trivially clear any floor.
        return 0.0 <= self.forge_authored_pct <= 1.0 and self.forge_authored_pct >= self.floor

    @property
    def closed(self) -> bool:
        """F-A1: the closure is the AND of all three conjuncts — any one false ⇒ NOT closed."""
        return bool(self.original_suite_pass and self.session_pass and self.floor_met)

    @property
    def disposition(self) -> str:
        """The deferred→ready flip (epiphany-report pattern). ``closed`` flips to the ready string;
        otherwise a ``deferred:`` disposition naming exactly which conjunct(s) blocked it."""
        if self.closed:
            return "closed-forge-convergence"
        missing = []
        if not self.original_suite_pass:
            missing.append("original-suite")
        if not self.session_pass:
            missing.append("session")
        if not self.floor_met:
            missing.append(f"pct<{self.floor:g}")
        return "deferred:" + ",".join(missing)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["floor_met"] = self.floor_met
        d["closed"] = self.closed
        d["disposition"] = self.disposition
        return d


def closure(target_dir: str, *, floor: float = DEFAULT_FLOOR) -> ClosureVerdict:
    """Compute the closure verdict for a re-authored target from its recorded measurements
    (``forge_closure.json``: ``original_suite_pass``, ``session_pass``, ``forge_authored_pct`` —
    written by the bar-(a)/T6 re-author run). A missing or partial record reads as NOT closed
    (every absent signal defaults False / 0.0), never closed by assumption (INV-1)."""
    path = os.path.join(target_dir, CLOSURE_RECORD)
    data: dict = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    # The floor is a PINNED POLICY threshold from the CALLER (pinned at the T5 budget gate) — it is
    # NEVER read back from the measured record. Reading it from the record would let a record
    # self-certify closure with `floor: 0.0` — a laundering channel (INV-1, N1).
    return ClosureVerdict(
        original_suite_pass=bool(data.get("original_suite_pass", False)),
        session_pass=bool(data.get("session_pass", False)),
        forge_authored_pct=float(data.get("forge_authored_pct", 0.0)),
        floor=floor,
    )


def record_closure(target_dir: str, verdict: ClosureVerdict) -> str:
    """Record the verdict next to the target (APU-S4-EXECUTOR-CLOSURE: the verdict is recorded).
    Returns the written path."""
    path = os.path.join(target_dir, VERDICT_RECORD)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(verdict.to_dict(), fh, indent=2, sort_keys=True)
    return path


__all__ = ["DEFAULT_FLOOR", "CLOSURE_RECORD", "VERDICT_RECORD", "ClosureVerdict",
           "closure", "record_closure"]
