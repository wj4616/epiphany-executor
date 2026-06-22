"""Field census (epiphany-executor S-P1-census, IC-P1c, INV-2, CV-05).

INV-2 / HG2-for-plans: every emitted field — plan-level AND per-step — must change executor
behavior, or be explicitly waived as metadata-only. The census:

  1. enumerates every plan-level + per-step key across a set of execution plans,
  2. binds each key to a downstream **consumer** (the executor layer that READS/branches on it),
     keyed against a static FIELD->CONSUMER map (behavior-sensitivity, not mere presence),
  3. produces a report that BLOCKS on (a) a key with no consumer and no waiver (silently dropped),
     and (b) a consumer that is declared for a key never seen in the corpus (present-but-unconsumed
     in the other direction — a stale binding), per CV-05.

The map is the single authority for "what reads what". When a new emitted field appears in the
corpus that the map does not cover, the census BLOCKS — that is the INV-2 enforcement: a new field
cannot be silently dropped; it must be wired to a consumer or explicitly waived.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _dc_field

# --- the authority: every known emitted key -> the consumer that reads/branches on it -----------
# A consumer name is a downstream executor layer (step) that is *behavior-sensitive* to the key.
# ``metadata-only`` is an explicit waiver: the key is retained (INV-2: never dropped) but does not
# steer behavior. A waiver is a deliberate, reviewable decision — not a silent gap.
PLAN_LEVEL_CONSUMERS: dict[str, str] = {
    "plan_id": "metadata-only (provenance; surfaced in telemetry brief)",
    "title": "metadata-only (provenance; surfaced in telemetry brief)",
    "source_spec": "S-P5-coverage (requirement-trace closure references the source spec)",
    "consumers": "metadata-only (declares this executor is the intended consumer; dogfood signal)",
    "rendering_note": "metadata-only (human render hint)",
    "gate_status": "S-P1-gate-defect (INV-17 start gate: verdict/gate)",
    "blocking_defects": "S-P1-gate-defect (INV-17: open defects halt before step 1)",
    "non_blocking_observations": "S-P5-telemetry (surfaced advisory; does not gate)",
    "requirement_preservation": "S-P5-coverage (coverage-closure reconciliation)",
    "build_order": "S-P2-scheduler (authoritative inter-layer sequence) + S-P1-importer (ordering)",
    "steps": "S-P1-importer (one step -> one node)",
    "structural_faults": "S-P1-gate-defect (INV-17: structural faults inform the halt)",
    "refinement_back_edges": "S-P4-review (append-only back-update channel; rule conditions)",
    "revisability_note": "metadata-only (records plan-versioning policy)",
    "removed_artifact": "metadata-only (records an artifact the plan dropped; provenance)",
    "schema_version": "schema-tolerant: S-P1-importer (fail-closed dialect/version gate, §4.5)",
    # harness/forge accommodation (additive; absent for generic plans). Consumed by S-P2-context:
    # context_builder.harness_forge_pack() branches on target_profile and injects harness_forge.
    "target_profile": "schema-tolerant: S-P2-context (selects harness-forge accommodation; default generic)",
    "harness_forge": "schema-tolerant: S-P2-context (provider-hint/harness-first/primitives context + self-clobber guard)",
    # epiphany-plan SCHEMA-VARIANT envelope (coverage_verdict/structural_verdict/execution_order +
    # graph keys). The importer (_coerce_schema_variant) maps these to the triad the executor reads,
    # so they are legitimately ABSENT from already-triad plans -> schema-tolerant (no stale-binding
    # BLOCK), and CONSUMED-via-coercion when present (no silent-drop BLOCK).
    "coverage_verdict": "schema-tolerant: S-P1-importer (coerced -> gate_status.verdict; INV-17 FAIL->HALT) + S-P5-coverage",
    "structural_verdict": "schema-tolerant: S-P1-importer (coerced -> gate_status.verdict/structural_faults; INV-17)",
    "execution_order": "schema-tolerant: S-P1-importer (coerced -> build_order) + S-P2-scheduler (topological order)",
    "requirement_ledger": "schema-tolerant: S-P5-coverage (obligation -> covered_by closure reconciliation)",
    "plan_meta": "metadata-only (provenance envelope: plan_id/title/source_spec/generated_by/target_profile nested here)",
    # integrated-pipeline carry-through (additive; harness-forge only; absent for generic plans, so
    # schema-tolerant — present-and-consumed on a harness plan, legitimately absent on a generic one,
    # never a stale-binding BLOCK). Each is READ by the executor closure layer (closure_gate), not
    # merely retained — so it is a real consumer entry, not metadata-only (F5/F8, INV-4).
    # The typed chain fields (solution_dir/stage/prev_stage/next_skill) stay NESTED under plan_meta
    # (Q-A default a), already covered by the plan_meta metadata-only entry — no top-level entry needed.
    "wiring_contract": "schema-tolerant: S-P5-closure (closure_gate.enforce_closure / facet_closure_report read the authored wiring_contract; the wiring-check gate)",
    "harness_ledger": "schema-tolerant: S-P5-closure (closure_gate.facet_closure_report ties each facet to the built skill; the anti-false-green tie)",
    "waived_facets": "schema-tolerant: S-P5-closure (closure report surfaces waived facets with reason; INV-6)",
    "roots": "metadata-only (DAG sources; scheduler derives the ready-front from per-step dependencies)",
    "leaves": "metadata-only (DAG sinks; provenance/telemetry; scheduler derives from dependencies)",
    "terminal_milestones": "metadata-only (semantic release tail; NOT required to equal leaves)",
    "graph_notes": "metadata-only (DAG narrative; human render hint)",
    "out_of_scope": "metadata-only (explicit non-goals/exclusions; recorded, never executed)",
}

STEP_LEVEL_CONSUMERS: dict[str, str] = {
    "step_id": "S-P1-importer (node id) + S-P3-lifecycle (recovery key)",
    "goal": "S-P2-context (look-behind/ahead summary) + S-P2-context (thinking-budget input)",
    "actions": "S-P3-effector-fanout (the in-step checklist the effector performs)",
    "inputs": "S-P2-context (resolved-input rendering) + S-P2-scheduler (data-flow)",
    "outputs": "S-P2-scheduler (write-set / conflict graph) + S-P5-coverage",
    "dependencies": "S-P2-scheduler (DAG edges) + S-P1-importer (prereq edges)",
    "integration_checks": "S-P3-dod (DoD) + S-P1-gate-defect (status BLOCKING DEFECT)",
    "acceptance_criteria": "S-P3-dod (two-class DoD; empty -> BLOCKED, INV-10)",
    "traces_to": "S-P5-coverage (requirement-coverage closure)",
    "traces_requirements": "schema-tolerant: S-P5-coverage (schema alias of traces_to; emitter uses traces_to)",
    "phase": "schema-tolerant: S-P2-scheduler (coarse layer hint; absent in current emit)",
    "refinement_back_edges": "schema-tolerant: S-P4-review (per-step back-update channel; plan-level in current emit)",
    # power-flywheel extra keys (real corpus): bound, not dropped.
    "emit_note": "metadata-only (emitter provenance note; surfaced in telemetry)",
    "gap_surfaced": "S-P1-gate-defect (a surfaced gap is treated like a non-blocking observation)",
    "is_gap_marker": "S-P5-coverage (a gap-marker step is excluded from executable coverage)",
    "resolved_bindings": "S-P2-context (pre-resolved input bindings feed look-behind)",
    # harness/forge accommodation (additive; absent for generic plans). Consumed by S-P2-context:
    # build_step_context() reads target_subsystem into the step context + the self-clobber guard.
    "target_subsystem": "schema-tolerant: S-P2-context (harness/forge subsystem focus + self-clobber target)",
    "obligation_class": "metadata-only (advisory obligation tag; the build-not-just-test gate lives in epiphany-plan coverage_audit)",
    # integrated-pipeline per-step carry-through: the wiring-row ids a capability-closure step covers.
    # schema-tolerant (harness plans only; absent on a generic plan). Consumed by the closure layer
    # (closure_gate bijection of authored wiring rows to built capabilities) — F5/F8, INV-4.
    "wiring_rows": "schema-tolerant: S-P5-closure (per-step wiring-row ids referenced by capability-closure steps; closure_gate bijection)",
}


@dataclass
class CensusFinding:
    scope: str        # 'plan' | 'step'
    key: str
    seen_in: list[str]
    consumer: str | None
    verdict: str      # 'CONSUMED' | 'WAIVED' | 'BLOCK-unconsumed' | 'BLOCK-stale-binding'


@dataclass
class CensusReport:
    findings: list[CensusFinding] = _dc_field(default_factory=list)

    @property
    def blocking(self) -> list[CensusFinding]:
        return [f for f in self.findings if f.verdict.startswith("BLOCK")]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def render(self) -> str:
        lines = ["# Field Census Report (INV-2 / IC-P1c / CV-05)", ""]
        lines.append(f"verdict: {'PASS' if self.passed else 'BLOCK'} "
                     f"({len(self.findings)} keys, {len(self.blocking)} blocking)")
        lines.append("")
        for f in self.findings:
            lines.append(f"- [{f.verdict}] {f.scope}:{f.key} "
                         f"(seen in {', '.join(f.seen_in) or '—'}) -> {f.consumer or 'NO CONSUMER'}")
        return "\n".join(lines)


def _is_waiver(consumer: str) -> bool:
    return consumer.startswith("metadata-only")


def _is_schema_tolerant(consumer: str) -> bool:
    """A ``schema-tolerant:`` consumer is wired for a plan.schema.json key the current emitter
    does NOT yet produce (the standing INV-12 schema<->emitter divergence, §4.6 item h). It is
    legitimately ABSENT from the corpus, so it must not trip the stale-binding BLOCK; when the
    emitter starts producing it, the consumer is ready (no silent drop)."""
    return consumer.startswith("schema-tolerant:")


def _stale_exempt(consumer: str) -> bool:
    return _is_waiver(consumer) or _is_schema_tolerant(consumer)


def _verdict(consumer: str) -> str:
    if _is_waiver(consumer):
        return "WAIVED"
    if _is_schema_tolerant(consumer):
        return "SCHEMA-TOLERANT"
    return "CONSUMED"


def census(plans: dict[str, dict]) -> CensusReport:
    """Enumerate every key across ``plans`` (name -> raw execution-plan dict) and bind each to a
    consumer. BLOCK on a key with no consumer (silent-drop) and on a declared consumer for a key
    the corpus never produced (stale binding). ``plans`` keys are corpus names for provenance."""
    report = CensusReport()

    # --- plan-level keys ---
    plan_seen: dict[str, list[str]] = {}
    for name, plan in plans.items():
        for k in plan:
            plan_seen.setdefault(k, []).append(name)
    for k, seen in sorted(plan_seen.items()):
        consumer = PLAN_LEVEL_CONSUMERS.get(k)
        if consumer is None:
            report.findings.append(CensusFinding("plan", k, seen, None, "BLOCK-unconsumed"))
        else:
            report.findings.append(CensusFinding("plan", k, seen, consumer, _verdict(consumer)))
    # stale binding: a plan-level consumer declared for a key never seen in the corpus
    # (schema-tolerant + metadata-only consumers are legitimately absent and exempt).
    for k, consumer in sorted(PLAN_LEVEL_CONSUMERS.items()):
        if k not in plan_seen and not _stale_exempt(consumer):
            report.findings.append(CensusFinding("plan", k, [], consumer, "BLOCK-stale-binding"))

    # --- per-step keys ---
    step_seen: dict[str, list[str]] = {}
    for name, plan in plans.items():
        keys_in_plan: set[str] = set()
        for s in plan.get("steps", []):
            if isinstance(s, dict):
                keys_in_plan |= set(s.keys())
        for k in keys_in_plan:
            step_seen.setdefault(k, []).append(name)
    for k, seen in sorted(step_seen.items()):
        consumer = STEP_LEVEL_CONSUMERS.get(k)
        if consumer is None:
            report.findings.append(CensusFinding("step", k, seen, None, "BLOCK-unconsumed"))
        else:
            report.findings.append(CensusFinding("step", k, seen, consumer, _verdict(consumer)))
    for k, consumer in sorted(STEP_LEVEL_CONSUMERS.items()):
        if k not in step_seen and not _stale_exempt(consumer):
            report.findings.append(CensusFinding("step", k, [], consumer, "BLOCK-stale-binding"))

    return report
