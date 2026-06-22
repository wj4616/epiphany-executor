"""solution_workspace — the canonical shared resolver for the integrated pipeline.

This is the SINGLE SOURCE OF TRUTH (INV-5). Identical byte-for-byte copies are
vendored into each pipeline skill's local scripts dir; a per-skill
`test_solution_workspace_in_sync` compares sha256 against this file so the copies
can never silently drift.

It provides a universal solution-workspace layer shared by every project domain:

    ~/docs/solution/<YYYY-MM-DD>-<slug>/
        solution.json          # workspace-root manifest (cross-stage join key)
        00-brief/  01-spec/  02-plan/  03-build/

plus, for harness-forge projects ONLY, a travelling `harness_ledger` and an
audited `--waiver` record. A *generic* project never gets a `harness_ledger`
key written anywhere (INV-1 byte-identity: absence, not an empty object).

Design rules honoured here:
- atomic writes (tmp file + os.replace) [APU-002]
- idempotent, forward-compatible deep-merge of the manifest (unknown keys from a
  newer stage are preserved) [APU-002]
- path-traversal rejection in slug / upstream [APU-022]
- no third-party dependencies; stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date as _date
from typing import Any, Iterable

# --- constants ---------------------------------------------------------------

SOLUTION_ROOT_ENV = "EPIPHANY_SOLUTION_ROOT"
DEFAULT_SOLUTION_ROOT = "~/docs/solution"
MANIFEST_NAME = "solution.json"
MANIFEST_SCHEMA = "solution-workspace/manifest@1"

# Stage subdir names, in pipeline order. The leading NN- prefix makes them sort.
STAGES: dict[str, str] = {
    "brief": "00-brief",
    "spec": "01-spec",
    "plan": "02-plan",
    "build": "03-build",
}

# The 8 harness facets (brief §-codes) + 6 context-pack facets. Used to seed and
# enumerate the harness_ledger. Order is stable for deterministic output.
HARNESS_FACETS: list[str] = ["G", "W", "V", "M", "B", "E", "O", "K"]
CONTEXT_PACK_FACETS: list[str] = [
    "capability_gaps", "harness_primitives", "grammar_cells",
    "correctness_basis", "machine_advantage", "invariants",
]
ALL_FACETS: list[str] = HARNESS_FACETS + CONTEXT_PACK_FACETS

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG_SAFE_RE = re.compile(r"[^a-z0-9._-]+")


# --- errors ------------------------------------------------------------------

class WorkspaceError(ValueError):
    """Raised on a rejected slug/upstream or a malformed workspace request."""


# --- path safety -------------------------------------------------------------

def solution_root() -> str:
    """The configured solution root, expanded. Override via env for tests."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get(SOLUTION_ROOT_ENV, DEFAULT_SOLUTION_ROOT)))


def _reject_traversal(value: str, *, field: str) -> None:
    """Reject any value that could escape the solution root via traversal."""
    if value is None:
        raise WorkspaceError(f"{field} is required")
    if ".." in value.split(os.sep) or ".." in value.replace("\\", "/").split("/"):
        raise WorkspaceError(f"path traversal rejected in {field}: {value!r}")
    if "\x00" in value:
        raise WorkspaceError(f"null byte rejected in {field}")


def sanitize_slug(slug: str) -> str:
    """Filesystem-safe slug: lowercase, non-alnum -> hyphen, collapse, trim.

    Traversal is rejected BEFORE sanitizing so a hostile ``../x`` cannot be
    silently scrubbed into a benign-looking slug.
    """
    if not slug or not str(slug).strip():
        raise WorkspaceError("slug is required and must be non-empty")
    _reject_traversal(str(slug), field="slug")
    cleaned = _SLUG_SAFE_RE.sub("-", str(slug).strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-._")
    if not cleaned:
        raise WorkspaceError(f"slug sanitized to empty: {slug!r}")
    return cleaned


def _validate_date(date: str | None) -> str:
    if date is None:
        return _date.today().isoformat()
    date = str(date)
    if not _DATE_RE.match(date):
        raise WorkspaceError(f"date must be YYYY-MM-DD, got {date!r}")
    return date


# --- workspace resolution ----------------------------------------------------

def workspace_name(slug: str, date: str | None = None) -> str:
    """The directory name `<YYYY-MM-DD>-<slug>` for a (slug, date)."""
    return f"{_validate_date(date)}-{sanitize_slug(slug)}"


def _is_workspace_dir(path: str) -> bool:
    return os.path.isfile(os.path.join(path, MANIFEST_NAME)) or \
        os.path.basename(os.path.normpath(path)) and \
        bool(re.match(r"^\d{4}-\d{2}-\d{2}-", os.path.basename(os.path.normpath(path))))


def _resolve_upstream(upstream: str) -> str:
    """Resolve a workspace path from an upstream pointer.

    `upstream` may be: a handoff.json path (reads solution_dir), a workspace dir,
    or a stage subdir (00-brief/.. inside a workspace). Returns the workspace
    root (the dir that holds solution.json), idempotently [APU-005].
    """
    _reject_traversal(str(upstream), field="upstream")
    up = os.path.abspath(os.path.expanduser(str(upstream)))

    # 1. a handoff.json (or any json carrying solution_dir)
    if os.path.isfile(up) and up.endswith(".json"):
        try:
            data = json.loads(_read_text(up) or "{}")
        except (json.JSONDecodeError, OSError):
            data = {}
        sd = data.get("solution_dir")
        if sd:
            return os.path.abspath(os.path.expanduser(str(sd)))
        # a manifest itself -> its parent is the workspace
        if os.path.basename(up) == MANIFEST_NAME:
            return os.path.dirname(up)
        # fall through: handoff sitting inside a stage subdir
        up = os.path.dirname(up)

    if os.path.isfile(up):
        up = os.path.dirname(up)

    # 2. a stage subdir -> parent workspace
    if os.path.basename(os.path.normpath(up)) in STAGES.values():
        parent = os.path.dirname(os.path.normpath(up))
        if os.path.isfile(os.path.join(parent, MANIFEST_NAME)) or _is_workspace_dir(parent):
            return parent

    # 3. a bare workspace dir
    return os.path.normpath(up)


def resolve(slug: str | None = None, date: str | None = None,
            upstream: str | None = None) -> str:
    """Resolve (and create) the canonical workspace dir; return its path.

    If `upstream` is given it wins — the SAME workspace is resolved from any
    upstream handoff / workspace dir / stage subdir (idempotent) [APU-001,005].
    Otherwise a `<date>-<slug>` workspace is created under the solution root.

    Always ensures the workspace dir, the four stage subdirs, and a baseline
    solution.json exist before returning.
    """
    if upstream:
        workspace = _resolve_upstream(upstream)
    else:
        if not slug:
            raise WorkspaceError("resolve() needs a slug or an upstream pointer")
        workspace = os.path.join(solution_root(), workspace_name(slug, date))

    os.makedirs(workspace, exist_ok=True)
    for sub in STAGES.values():
        os.makedirs(os.path.join(workspace, sub), exist_ok=True)
    _ensure_manifest(workspace, slug=slug, date=date)
    return workspace


def stage_subdir(workspace: str, stage: str) -> str:
    """Return (creating) the stage subdir path for `stage` [APU-003]."""
    if stage not in STAGES:
        raise WorkspaceError(f"unknown stage {stage!r}; expected one of {list(STAGES)}")
    path = os.path.join(workspace, STAGES[stage])
    os.makedirs(path, exist_ok=True)
    return path


# --- manifest read / atomic merge --------------------------------------------

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _atomic_write_json(path: str, data: dict) -> None:
    """Write JSON atomically: tmp in the same dir + os.replace (APU-002, C-4)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".solution.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _deep_merge(base: dict, incoming: dict) -> dict:
    """Forward-compatible deep merge: incoming wins on scalars; dicts recurse;
    unknown keys on EITHER side are preserved [APU-002]. Lists are replaced
    (a stage owns its own list values), not concatenated."""
    out = dict(base)
    for key, val in incoming.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def read_manifest(workspace: str) -> dict:
    """Read solution.json (or {} if absent)."""
    path = os.path.join(workspace, MANIFEST_NAME)
    if not os.path.isfile(path):
        return {}
    try:
        return json.loads(_read_text(path) or "{}")
    except json.JSONDecodeError:
        return {}


def _ensure_manifest(workspace: str, *, slug: str | None, date: str | None) -> dict:
    """Create a baseline manifest if absent. Generic by default: NO harness_ledger
    key (INV-1). The baseline carries only universal fields."""
    existing = read_manifest(workspace)
    if existing:
        return existing
    name = os.path.basename(os.path.normpath(workspace))
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", name)
    derived_date = m.group(1) if m else None
    derived_slug = m.group(2) if m else None
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "slug": (sanitize_slug(slug) if slug else derived_slug) or name,
        "date": _validate_date(date) if date else (derived_date or _date.today().isoformat()),
        "stages": {},
    }
    _atomic_write_json(os.path.join(workspace, MANIFEST_NAME), manifest)
    return manifest


def update_stage(workspace: str, stage: str, entry: dict) -> dict:
    """Idempotently merge a stage entry into solution.json under stages.<stage>.

    Atomic + forward-compatible: a second write preserves prior stages and any
    unknown keys written by a newer stage [APU-002, R-10]. Returns the new
    manifest. The harness_ledger / waivers (if present in `entry`) ride the same
    deep-merge but are only written by harness callers (the generic path never
    passes them) — INV-1.
    """
    if stage not in STAGES:
        raise WorkspaceError(f"unknown stage {stage!r}")
    current = read_manifest(workspace)
    if not current:
        current = _ensure_manifest(workspace, slug=None, date=None)
    incoming = {"stages": {stage: dict(entry)}}
    merged = _deep_merge(current, incoming)
    _atomic_write_json(os.path.join(workspace, MANIFEST_NAME), merged)
    return merged


# --- harness layer (harness-forge only) --------------------------------------

def seed_ledger(facets: Iterable[str] | None = None, *, source_stage: str = "brief",
                statuses: dict[str, str] | None = None) -> dict:
    """Build a fresh harness_ledger dict: facet -> record. HARNESS ONLY.

    Each record: {facet, present, source_stage, detail_ref, status, waiver_reason?}.
    `statuses` overrides per-facet status (full|thin|missing|waived); default
    'missing' so an unset facet must be explicitly satisfied downstream.
    """
    facets = list(facets) if facets is not None else list(ALL_FACETS)
    statuses = statuses or {}
    ledger: dict[str, Any] = {}
    for f in facets:
        status = statuses.get(f, "missing")
        ledger[f] = {
            "facet": f,
            "present": status in ("full", "thin", "waived"),
            "source_stage": source_stage,
            "detail_ref": None,
            "status": status,
        }
    return ledger


def update_ledger(workspace: str, facets: dict[str, dict]) -> dict:
    """Merge harness_ledger facet records into the manifest. HARNESS ONLY.

    Never call on a generic project — doing so would write a harness_ledger key
    and break byte-identity (INV-1). Returns the new manifest.
    """
    current = read_manifest(workspace)
    if not current:
        current = _ensure_manifest(workspace, slug=None, date=None)
    existing = current.get("harness_ledger", {})
    merged_ledger = _deep_merge(existing, facets)
    merged = _deep_merge(current, {"harness_ledger": merged_ledger})
    _atomic_write_json(os.path.join(workspace, MANIFEST_NAME), merged)
    return merged


def record_waiver(workspace: str, facet: str, reason: str) -> dict:
    """Record an audited --waiver for a facet: status->waived + reason, plus an
    append-only entry in manifest.waivers. HARNESS ONLY [APU-016, INV-6]."""
    if not reason or not str(reason).strip():
        raise WorkspaceError("a waiver must carry a non-empty reason (INV-6)")
    current = read_manifest(workspace)
    if not current:
        current = _ensure_manifest(workspace, slug=None, date=None)
    ledger = dict(current.get("harness_ledger", {}))
    rec = dict(ledger.get(facet, {"facet": facet, "source_stage": "waiver", "detail_ref": None}))
    rec["status"] = "waived"
    rec["present"] = True
    rec["waiver_reason"] = str(reason).strip()
    ledger[facet] = rec
    waivers = list(current.get("waivers", []))
    waivers.append({"facet": facet, "reason": str(reason).strip()})
    merged = _deep_merge(current, {"harness_ledger": ledger, "waivers": waivers})
    _atomic_write_json(os.path.join(workspace, MANIFEST_NAME), merged)
    return merged


# --- handoff helper ----------------------------------------------------------

def handoff_chain_fields(workspace: str, stage: str, *,
                         next_skill: str | None = None,
                         prev_stage: str | None = None) -> dict:
    """The typed handoff-chain fields every stage's handoff.json must carry
    so the next stage auto-discovers the workspace from the handoff alone
    [APU-004]. Returns a dict to splat into the handoff payload."""
    if stage not in STAGES:
        raise WorkspaceError(f"unknown stage {stage!r}")
    order = list(STAGES.keys())
    idx = order.index(stage)
    auto_prev = order[idx - 1] if idx > 0 else None
    auto_next = order[idx + 1] if idx + 1 < len(order) else None
    return {
        "solution_dir": os.path.abspath(workspace),
        "stage": stage,
        "prev_stage": prev_stage if prev_stage is not None else auto_prev,
        "next_skill": next_skill or (f"epiphany-{auto_next}" if auto_next else None),
    }
