"""Per-step context assembly + AI-advantage allocation (S-P2-context, AX-02/03/07, INV-2/11).

Three machine-advantage levers, all advisory-safe (a wrong/empty prior never relaxes a gate):
  - **AX-03 1M hold-all** — keep the whole plan + completed ledger resident while it fits the
    context budget; degrade to tiered summaries then bounded-window streaming above ~70%.
  - **AX-02 thinking-budget** — scale reasoning depth by blast-radius / reversibility / fan-out /
    defect-proximity. NEVER down-tiers a step out of a gate; default-over-allocate on uncertainty;
    an irreversible step is always DEEP.
  - **AX-07 memory priming** — Memory priors may RAISE a tier or hint scheduling, never lower a
    tier below its safety floor and never skip a check (advisory-only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ResidentMode(str, Enum):
    HOLD_ALL = "hold-all"
    TIERED_SUMMARY = "tiered-summary"
    WINDOWED_STREAM = "windowed-stream"


class ThinkingTier(str, Enum):
    NONE = "none"
    MINIMAL = "minimal"
    STANDARD = "standard"
    DEEP = "deep"


_TIER_ORDER = [ThinkingTier.NONE, ThinkingTier.MINIMAL, ThinkingTier.STANDARD, ThinkingTier.DEEP]


def _max_tier(a: ThinkingTier, b: ThinkingTier) -> ThinkingTier:
    return a if _TIER_ORDER.index(a) >= _TIER_ORDER.index(b) else b


@dataclass
class StepContext:
    step_id: str
    look_behind: list[str] = field(default_factory=list)   # ACCEPTED predecessor step_ids
    look_ahead: list[str] = field(default_factory=list)    # downstream dependent step_ids
    predecessor_deltas: dict = field(default_factory=dict)  # step_id -> ledger state_delta
    resident_mode: ResidentMode = ResidentMode.HOLD_ALL
    thinking_tier: ThinkingTier = ThinkingTier.STANDARD
    tier_rationale: list[str] = field(default_factory=list)
    # harness/forge accommodation (additive; populated only when target_profile == 'harness-forge')
    target_profile: str = "generic"
    target_subsystem: str | None = None
    harness_forge_context: list[str] = field(default_factory=list)  # extra reference context lines
    self_clobber_paths: list[str] = field(default_factory=list)     # outputs that hit live skill/harness/forge dirs


# --- harness/forge accommodation (additive; see ~/docs/epiphany/harness-forge-pipeline-integration.md) ---

import os

# LIVE install roots a self-modifying harness/forge plan could clobber IN PLACE while it runs.
# Matched as absolute-path PREFIXES (not substrings) so a safe out-dir emit whose path merely
# *contains* one of these tokens (e.g. /tmp/out/.../graph.json) is NOT flagged. Relative output
# paths are resolved against the workspace root (~), since plan outputs are workspace-relative.
_LIVE_DIR_ROOTS = ("~/.claude/skills", "~/projects/goatcs-harness")  # real dirs → path-boundary match
_LIVE_FAMILY_PREFIXES = ("~/projects/epiphany-",)                    # name-prefix family (epiphany-report, …)


def _resolve_output(path: str) -> str:
    """Resolve a plan output path to absolute. Absolute paths are kept; relative ones are anchored
    at the workspace root (~), matching how plan outputs are written (workspace-relative)."""
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.normpath(os.path.join(os.path.expanduser("~"), p))
    return os.path.normpath(p)


def _is_live_path(path: str, out_dir: str | None = None) -> bool:
    """True iff `path` resolves INTO a live install dir AND is not under an explicit safe out_dir."""
    resolved = _resolve_output(path)
    if out_dir:
        od = _resolve_output(out_dir)
        if resolved == od or resolved.startswith(od + os.sep):
            return False  # explicitly redirected to a safe out-dir → not a clobber
    for pre in _LIVE_DIR_ROOTS:
        root = os.path.normpath(os.path.expanduser(pre))
        if resolved == root or resolved.startswith(root + os.sep):
            return True
    for pre in _LIVE_FAMILY_PREFIXES:
        root = os.path.normpath(os.path.expanduser(pre))
        if resolved.startswith(root):  # family prefix, e.g. ~/projects/epiphany-report
            return True
    return False


def harness_forge_pack(plan_meta: dict | None) -> dict | None:
    """Return the forwarded context-pack iff the plan declares target_profile == 'harness-forge'.
    Absent/generic ⇒ None (no accommodation). Behavior-sensitive consumer of plan_meta.target_profile
    + plan_meta.harness_forge (INV-2)."""
    if not plan_meta or plan_meta.get("target_profile") != "harness-forge":
        return None
    return plan_meta.get("harness_forge") or {}


def harness_forge_context_lines(pack: dict, step: dict | None = None) -> list[str]:
    """Extra reference context injected into a step when the plan targets the harness/forge system.
    Pure derivation from the pack + step — no fabrication; empty pack ⇒ empty list."""
    if pack is None:
        return []
    lines: list[str] = []
    if pack.get("provider_hint"):
        lines.append(f"provider-hint: dispatch heavy harness/forge runs via --provider {pack['provider_hint']} "
                     f"(claude-cli times out on large graphs).")
    if pack.get("harness_first"):
        lines.append("harness-first: a harness primitive must land+tested BEFORE the forge step that exploits it.")
    if pack.get("harness_primitives"):
        lines.append("harness-primitives in scope: " + ", ".join(map(str, pack["harness_primitives"])))
    lines.append("harness exit-code conventions: exit-7 = static gate fail; exit-11 = inline reasoning pause.")
    if step:
        sub = (step.get("target_subsystem") if isinstance(step, dict) else None)
        if sub:
            lines.append(f"target-subsystem focus: {sub}")
    return lines


def detect_self_clobber(step: dict | None, pack: dict | None) -> list[str]:
    """When the plan is self_modifying, flag any step output that targets a LIVE skill/harness/forge
    dir IN PLACE — the running code could be overwritten mid-execution. Generalizes selfhost.py's
    bespoke per-step-id dry-run guard. An output redirected under the pack's explicit `out_dir` is
    exempt (the whole point of an out-dir is a safe non-clobber emit). Path-prefix matching (not
    substring), so a safe /tmp/out/... path that merely contains a live token is NOT flagged.
    Returns the offending output paths (empty ⇒ no risk / not applicable)."""
    if not pack or not pack.get("self_modifying") or not isinstance(step, dict):
        return []
    out_dir = pack.get("out_dir")
    outs = step.get("outputs") or []
    return [o for o in outs if isinstance(o, str) and _is_live_path(o, out_dir)]


def resident_context_mode(plan_chars: int, ledger_chars: int,
                          budget_chars: int = 1_000_000, threshold: float = 0.70) -> ResidentMode:
    """AX-03: hold the whole plan+ledger resident by default; above `threshold` of budget keep
    full plan + per-step summaries (tiered); only stream when even the plan alone overflows."""
    if budget_chars <= 0:
        return ResidentMode.WINDOWED_STREAM
    used = (plan_chars + ledger_chars) / budget_chars
    if used <= threshold:
        return ResidentMode.HOLD_ALL
    if plan_chars / budget_chars <= threshold:
        return ResidentMode.TIERED_SUMMARY
    return ResidentMode.WINDOWED_STREAM


def allocate_thinking_tier(contract: dict, *, fan_out: int = 0, reversibility: str = "local-mutating",
                           defect_adjacent: bool = False) -> tuple[ThinkingTier, list[str]]:
    """AX-02: tier = f(blast_radius, reversibility, fan_out, defect_proximity). Returns the tier
    and a rationale. An irreversible/unknown-effect step, a blocking_defect-adjacent step, or a
    high-fan-out hub is DEEP. Never returns below the safety floor.
    """
    why: list[str] = []
    tier = ThinkingTier.STANDARD

    if reversibility in ("externally-irreversible", "unknown"):
        tier = _max_tier(tier, ThinkingTier.DEEP)
        why.append(f"reversibility={reversibility} -> DEEP (irreversible/unprovable, never down-tiered)")
    if defect_adjacent:
        tier = _max_tier(tier, ThinkingTier.DEEP)
        why.append("adjacent to a blocking_defect -> DEEP")
    if fan_out >= 3:
        tier = _max_tier(tier, ThinkingTier.DEEP)
        why.append(f"fan_out={fan_out} (high-fan-out hub) -> DEEP")

    # mechanical, output-disjoint, reversible leaf with no dependents: minimal is allowed.
    dod = contract.get("dod") or {}
    n_criteria = len(dod.get("acceptance_criteria") or []) + len(dod.get("integration_checks") or [])
    if (tier == ThinkingTier.STANDARD and reversibility == "local-mutating"
            and fan_out == 0 and n_criteria <= 1 and not defect_adjacent):
        tier = ThinkingTier.MINIMAL
        why.append("mechanical reversible leaf, <=1 criterion, no dependents -> MINIMAL")

    if not why:
        why.append("default STANDARD")
    return tier, why


def apply_memory_priors(tier: ThinkingTier, priors: dict | None) -> tuple[ThinkingTier, list[str]]:
    """AX-07: a prior may only RAISE the tier (advisory). An empty/wrong prior is a no-op — the
    safety floor from `allocate_thinking_tier` stands (fail-safe with empty memory)."""
    if not priors:
        return tier, []
    suggested = priors.get("suggested_tier")
    note: list[str] = []
    if suggested in {t.value for t in ThinkingTier}:
        raised = _max_tier(tier, ThinkingTier(suggested))
        if raised != tier:
            note.append(f"memory prior raised tier {tier.value} -> {raised.value} (advisory)")
        return raised, note
    return tier, note


def build_step_context(contracts: dict[str, dict], step_id: str, dag: dict[str, set[str]],
                       *, accepted: set[str] | None = None, ledger_deltas: dict | None = None,
                       plan_chars: int = 0, ledger_chars: int = 0,
                       memory_priors: dict | None = None,
                       plan_meta: dict | None = None, step: dict | None = None) -> StepContext:
    """Assemble look-behind (ACCEPTED predecessors + their ledger state_delta) and look-ahead
    (downstream dependents, INV-11), choose the resident mode, and allocate the thinking tier.

    When the plan declares `target_profile == 'harness-forge'`, additionally inject harness/forge
    reference context and bias the thinking tier (advisory raise-only) for self-modifying / forge
    steps. All harness/forge behavior is gated on the pack; a generic plan is byte-identical."""
    accepted = accepted or set()
    ledger_deltas = ledger_deltas or {}
    prereqs = dag.get(step_id, set())
    look_behind = sorted(p for p in prereqs if p in accepted)
    look_ahead = sorted(s for s, deps in dag.items() if step_id in deps)
    pred_deltas = {p: ledger_deltas[p] for p in look_behind if p in ledger_deltas}

    c = contracts[step_id]
    from .scheduler import static_effect_class  # local import avoids a cycle at module load
    rev = static_effect_class(c)
    tier, why = allocate_thinking_tier(c, fan_out=len(look_ahead), reversibility=rev)
    tier, mnote = apply_memory_priors(tier, memory_priors)

    # --- harness/forge accommodation (additive; default-off) ---
    pack = harness_forge_pack(plan_meta)
    profile = "harness-forge" if pack is not None else "generic"
    sub = step.get("target_subsystem") if isinstance(step, dict) else None
    hf_lines: list[str] = []
    clobber: list[str] = []
    hf_note: list[str] = []
    if pack is not None:
        hf_lines = harness_forge_context_lines(pack, step)
        clobber = detect_self_clobber(step, pack)
        if clobber:
            raised = _max_tier(tier, ThinkingTier.DEEP)
            if raised != tier:
                hf_note.append(f"self-clobber risk on {clobber} -> DEEP (modifies live harness/forge/skill)")
            tier = raised

    return StepContext(
        step_id=step_id,
        look_behind=look_behind,
        look_ahead=look_ahead,
        predecessor_deltas=pred_deltas,
        resident_mode=resident_context_mode(plan_chars, ledger_chars),
        thinking_tier=tier,
        tier_rationale=why + mnote + hf_note,
        target_profile=profile,
        target_subsystem=sub,
        harness_forge_context=hf_lines,
        self_clobber_paths=clobber,
    )
