"""INV-5 single-source resolver enforcement (S1).

The vendored copy of solution_workspace.py MUST be byte-identical to the
canonical goatcs-harness/shared/solution_workspace.py. We pin the canonical
sha256 here; the vendored copy is checked against it, so editing the vendored
copy fails this test (R-12). When the canonical source is locatable (a sibling
goatcs-harness checkout, or SOLUTION_WORKSPACE_CANONICAL env), we ALSO assert the
pin still equals the canonical hash, so the pin cannot silently go stale.
"""
from __future__ import annotations

import hashlib
import os

# Pinned sha256 of goatcs-harness/shared/solution_workspace.py (the canonical).
# If you intentionally change the canonical resolver, regenerate every vendored
# copy AND update this constant in all four skills.
CANONICAL_SHA256 = "6a04161b6bbd3affe8e1d806018e79e9987fe437a2322acb4ab179d4c75b4bb9"

_HERE = os.path.dirname(os.path.abspath(__file__))
VENDORED = os.path.normpath(os.path.join(_HERE, "..", "epiphany_executor", "solution_workspace.py"))


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _find_canonical() -> str | None:
    env = os.environ.get("SOLUTION_WORKSPACE_CANONICAL")
    if env and os.path.isfile(env):
        return env
    cur = _HERE
    for _ in range(8):
        cur = os.path.dirname(cur)
        cand = os.path.join(cur, "goatcs-harness", "shared", "solution_workspace.py")
        if os.path.isfile(cand):
            return cand
    return None


def test_vendored_copy_matches_pinned_canonical():
    assert os.path.isfile(VENDORED), f"vendored resolver missing: {VENDORED}"
    assert _sha256(VENDORED) == CANONICAL_SHA256, (
        "vendored solution_workspace.py drifted from the canonical hash — "
        "regenerate the vendored copy from goatcs-harness/shared/ (INV-5)"
    )


def test_pin_matches_canonical_source_when_available():
    canon = _find_canonical()
    if canon is None:
        import pytest
        pytest.skip("canonical goatcs-harness not co-located; pin-only check applies")
    assert _sha256(canon) == CANONICAL_SHA256, (
        "the canonical resolver changed but the pinned CANONICAL_SHA256 was not "
        "updated — vendored copies are now out of date (INV-5)"
    )
