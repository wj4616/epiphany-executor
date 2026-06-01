"""Pre-execution effect classification — v1 GATE-ONLY (S-P5-effect-class, INV-15/13/5, F-03/11).

`effect_class` is determined BEFORE a command runs (INV-15), conservative default
`externally-irreversible` for anything unclassifiable. The STATIC per-effect-class footprint for
the SCHEDULER is published at the contract layer (CV-02, see scheduler.static_effect_class); THIS
module does the pre-execution PER-COMMAND classification used for GATING, plus the
runtime/measured footprint that feeds the sentinel + drift/coverage POST-HOC (it never gates
scheduling).

v1 reliability is GATE-ONLY (INV-13): an externally-irreversible command WITHOUT a server-side
idempotency token is GATED (halt for human confirm, no auto-resume). The idempotency-token /
commit-then-replay auto-resume branch is INERT until the S-P7 effect-ledger substrate exists —
calling it in v1 asserts-fails (the reliability claim never exceeds the v1 mechanism).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .scheduler import _IRREVERSIBLE_MARKERS


class EffectClass(str, Enum):
    PURE = "pure"
    LOCAL_MUTATING = "local-mutating"
    EXTERNALLY_IRREVERSIBLE = "externally-irreversible"


_READONLY_PREFIXES = ("cat ", "ls ", "grep ", "rg ", "find ", "head ", "tail ", "echo ",
                      "test ", "stat ", "wc ", "diff ", "git status", "git log", "git diff",
                      "pytest", "python -m pytest", "ruff check", "mypy")
_LOCAL_MUTATING_MARKERS = (">", ">>", "touch ", "mkdir ", "rm ", "mv ", "cp ", "sed -i",
                           "git add", "git commit", "git checkout", "write", "edit")


def classify_command(cmd: str) -> EffectClass:
    """Pre-execution per-command classification (INV-15). Conservative: anything that names an
    external/irreversible marker is EXTERNALLY_IRREVERSIBLE; a read-only command is PURE; a
    local file mutation is LOCAL_MUTATING; ANYTHING ELSE defaults to EXTERNALLY_IRREVERSIBLE
    (unclassifiable = treat as irreversible)."""
    low = str(cmd).strip().lower()
    if not low:
        return EffectClass.EXTERNALLY_IRREVERSIBLE
    if any(m in low for m in _IRREVERSIBLE_MARKERS):
        return EffectClass.EXTERNALLY_IRREVERSIBLE
    # a write/redirect marker makes it local-mutating REGARDLESS of the command prefix
    # (e.g. `echo hi > out.txt` writes a file even though it starts with a read-only verb).
    if any(m in low for m in _LOCAL_MUTATING_MARKERS):
        return EffectClass.LOCAL_MUTATING
    if any(low.startswith(p) for p in _READONLY_PREFIXES):
        return EffectClass.PURE
    return EffectClass.EXTERNALLY_IRREVERSIBLE   # conservative default (INV-15)


@dataclass
class GateDecision:
    effect_class: EffectClass
    gated: bool
    reason: str


def gating_decision(effect_class: EffectClass, *, has_idempotency_token: bool = False) -> GateDecision:
    """v1 GATE-ONLY (INV-13): an externally-irreversible effect WITHOUT a server-side idempotency
    token is GATED (human confirm, no auto-resume). pure/local-mutating proceed."""
    if effect_class is EffectClass.EXTERNALLY_IRREVERSIBLE and not has_idempotency_token:
        return GateDecision(effect_class, gated=True,
                            reason="externally-irreversible without idempotency token -> human gate (INV-13 v1)")
    return GateDecision(effect_class, gated=False, reason="reversible or idempotent -> proceed")


def classify_step(contract: dict) -> list[GateDecision]:
    """Classify every command in a step's `actions` pre-execution and return the gate decisions.
    A step is gated iff any of its commands is gated."""
    actions = contract.get("actions") or []
    decisions: list[GateDecision] = []
    for a in actions:
        decisions.append(gating_decision(classify_command(a if isinstance(a, str) else str(a))))
    return decisions


def step_is_gated(contract: dict) -> bool:
    return any(d.gated for d in classify_step(contract))


# --- v1 inert auto-resume branch (unlocked by the S-P7 effect-ledger substrate) ---

class AutoResumeNotAvailable(Exception):
    """INV-13: auto-resume of irreversible effects is a v2 capability (commit-then-replay).
    The branch is inert in v1 — invoking it asserts-fails so the reliability claim never exceeds
    the v1 gate-only mechanism."""


def auto_resume_irreversible(*_args, **_kwargs):
    """v1: UNREACHABLE. Raises until the S-P7 effect-ledger substrate (commit-then-replay,
    idempotency-token table) lands and re-enables it."""
    raise AutoResumeNotAvailable(
        "irreversible auto-resume is gated until the S-P7 effect-ledger substrate exists (INV-13)")
