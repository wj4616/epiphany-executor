"""S4 / T4 — epiphany-executor convergence closure gate (APU-S4-EXECUTOR-CLOSURE, INV-1).

Exercises the closure gate against a STUB target: the three conjuncts (original-suite ∧ session ∧
pct≥floor) AND correctly (F-A1: any one false ⇒ NOT closed), the disposition flips deferred→ready,
the floor uses ≥ at the boundary, a missing record reads NOT closed (never closed by assumption),
and the verdict is recorded.
"""

from __future__ import annotations

import json
import os

import pytest

from epiphany_executor.convergence import (
    CLOSURE_RECORD,
    VERDICT_RECORD,
    ClosureVerdict,
    closure,
    record_closure,
)


def _write(target_dir, **fields):
    with open(os.path.join(target_dir, CLOSURE_RECORD), "w", encoding="utf-8") as fh:
        json.dump(fields, fh)


def test_all_three_conjuncts_true_closes(tmp_path):
    _write(tmp_path, original_suite_pass=True, session_pass=True, forge_authored_pct=0.95, floor=0.90)
    v = closure(str(tmp_path))
    assert v.closed is True
    assert v.disposition == "closed-forge-convergence"


@pytest.mark.parametrize("drop", ["original_suite_pass", "session_pass"])
def test_any_false_boolean_conjunct_blocks_closure(tmp_path, drop):
    fields = dict(original_suite_pass=True, session_pass=True, forge_authored_pct=0.95, floor=0.90)
    fields[drop] = False
    _write(tmp_path, **fields)
    v = closure(str(tmp_path))
    assert v.closed is False
    assert v.disposition.startswith("deferred:")


def test_pct_below_floor_blocks_closure(tmp_path):
    _write(tmp_path, original_suite_pass=True, session_pass=True, forge_authored_pct=0.89, floor=0.90)
    v = closure(str(tmp_path))
    assert v.closed is False and v.floor_met is False
    assert "pct<0.9" in v.disposition


def test_pct_exactly_at_floor_is_met(tmp_path):
    _write(tmp_path, original_suite_pass=True, session_pass=True, forge_authored_pct=0.90, floor=0.90)
    v = closure(str(tmp_path))
    assert v.floor_met is True and v.closed is True


def test_missing_record_is_not_closed_by_assumption(tmp_path):
    v = closure(str(tmp_path))                     # no forge_closure.json present
    assert v.closed is False
    assert v.original_suite_pass is False and v.session_pass is False
    assert v.forge_authored_pct == 0.0


def test_partial_record_defaults_missing_signals_false(tmp_path):
    _write(tmp_path, original_suite_pass=True)     # session + pct absent
    v = closure(str(tmp_path))
    assert v.closed is False
    assert v.session_pass is False and v.forge_authored_pct == 0.0


def test_disposition_names_every_blocking_conjunct(tmp_path):
    v = ClosureVerdict(original_suite_pass=False, session_pass=False, forge_authored_pct=0.0, floor=0.9)
    d = v.disposition
    assert "original-suite" in d and "session" in d and "pct<0.9" in d


def test_record_closure_writes_the_verdict(tmp_path):
    v = ClosureVerdict(original_suite_pass=True, session_pass=True, forge_authored_pct=0.95, floor=0.9)
    path = record_closure(str(tmp_path), v)
    assert path.endswith(VERDICT_RECORD)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["closed"] is True and saved["disposition"] == "closed-forge-convergence"
    assert saved["forge_authored_pct"] == 0.95


def test_floor_override_argument_used_when_record_omits_floor(tmp_path):
    _write(tmp_path, original_suite_pass=True, session_pass=True, forge_authored_pct=0.85)
    assert closure(str(tmp_path), floor=0.80).closed is True       # 0.85 ≥ 0.80
    assert closure(str(tmp_path), floor=0.90).closed is False      # 0.85 < 0.90


def test_record_floor_cannot_launder_closure(tmp_path):
    # N1: a record carrying a permissive floor must NOT override the caller's pinned policy floor —
    # else a buggy/colluding writer self-certifies convergence at ~0% authorship (INV-1 laundering).
    _write(tmp_path, original_suite_pass=True, session_pass=True, forge_authored_pct=0.10, floor=0.0)
    v = closure(str(tmp_path), floor=0.90)
    assert v.floor == 0.90 and v.closed is False                   # the record's floor=0.0 is ignored


def test_nonsensical_pct_above_one_does_not_close(tmp_path):
    # N2: forge_authored_pct is a fraction by construction; a >1.0 value is a measurement error and
    # must fail-closed, not trivially clear the floor.
    _write(tmp_path, original_suite_pass=True, session_pass=True, forge_authored_pct=99.0, floor=0.90)
    v = closure(str(tmp_path))
    assert v.floor_met is False and v.closed is False
