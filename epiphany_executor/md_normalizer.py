"""Markdown -> execution-plan-dict normalizers (epiphany-executor S-P1, tracker item (b)).

**Promoted to the harness as the single source.** The deterministic epiphany-plan ingest is now a
harness builtin tool (`plan.normalize_md`, `goatcs_harness/tool_registry.py`) backed by
`goatcs_harness.plan_normalize`, so the executor's `ingest_plan` node is a tool node, not a model
call. This module re-exports the canonical implementation to keep existing skill imports + tests
working and to resolve the harness/skill duplication (STATE GH-1) — a single source of truth.

Public API (unchanged):
  * ``normalize_plan_md(text)``  — epiphany-plan default Markdown (``### <step_id>`` blocks).
  * ``normalize_brainstorming_md(text)`` — best-effort section-per-step normalization.
Both return ``(plan_dict, lossy_fields)``.
"""
from __future__ import annotations

from goatcs_harness.plan_normalize import (  # noqa: F401  (re-export — canonical home is the harness)
    normalize_brainstorming_md,
    normalize_plan_md,
)

__all__ = ["normalize_plan_md", "normalize_brainstorming_md"]
