"""Markdown -> execution-plan-dict normalizers (epiphany-executor S-P1, tracker item (b)).

These live in the EXECUTOR skill (NOT the harness): they convert an epiphany-plan **Markdown**
document, or an unstructured **brainstorming** Markdown document, into the same execution-plan
dict that the harness ``epiphany-plan`` importer consumes (the JSON shape, §4.6). The harness
importer is the single ingest authority; this module only re-shapes Markdown into its input.

Two entry points (spec §4.2):
  * ``normalize_plan_md(text)``  — epiphany-plan default Markdown (``### <step_id>`` blocks with
    ``- **field:**`` lines, a ``## Coverage Verdict`` block, an ``## Execution Order`` list).
  * ``normalize_brainstorming_md(text)`` — best-effort: each ``#``/``##`` section becomes a step;
    missing per-step fields are emitted empty and recorded in ``lossy_fields[]`` (degraded !=
    authoritative); zero declared dependencies -> document-order fallback.

Both return ``(plan_dict, lossy_fields)``. ``plan_dict`` carries the epiphany-plan triad
(``build_order`` + ``steps`` + ``gate_status``) so it round-trips through the harness importer.
"""
from __future__ import annotations

import re

# a step header: '### <step_id> — <optional title>' (em-dash or hyphen or none)
_STEP_HEADER = re.compile(r"^###\s+(?P<sid>[A-Za-z0-9][\w.\-]*)\s*(?:[—\-]\s*(?P<title>.*))?$")
# a field line: '- **field:** value'
_FIELD_LINE = re.compile(r"^-\s+\*\*(?P<field>[A-Za-z0-9_]+):\*\*\s*(?P<val>.*)$")
# a sub-bullet under a field: '  - item'  or  '  1. item'
_SUBITEM = re.compile(r"^\s+(?:-|\d+\.)\s+(?P<item>.*)$")

# per-step fields the executor cares about; everything mapped to the JSON-shape keys.
_LIST_FIELDS = {"actions", "inputs", "outputs", "dependencies", "acceptance_criteria",
                "traces_to", "traces_requirements", "refinement_back_edges"}
_SCALAR_FIELDS = {"goal", "phase"}

_NONE_TOKENS = {"(none)", "none", "n/a", "-", ""}


def _is_none_value(v: str) -> bool:
    return v.strip().lower() in _NONE_TOKENS


def _split_inline_list(val: str) -> list[str]:
    """An inline field value may be a single item or a ';'/',' separated list. We split on ';'
    first (the emitter's primary list separator in inline form), else treat as one item."""
    val = val.strip()
    if not val or _is_none_value(val):
        return []
    if ";" in val:
        return [p.strip() for p in val.split(";") if p.strip()]
    return [val]


def _clean_dep(raw: str):
    """A Markdown dependency bullet is ``` `S-step-id` — kind: data · edge_class: ... ```.

    Extract the bare step_id; when a ``kind``/``edge_class`` annotation is present, emit the TYPED
    dep form ``{on, kind, edge_class}`` so the importer preserves the edge_class (INV-18: when
    typed deps ARE present, edge_class is used as specified). Otherwise return a bare step_id
    string (degrades to an ordering prerequisite)."""
    raw = raw.strip()
    if not raw or _is_none_value(raw):
        return None
    head, _, annot = raw.partition("—")
    if "—" not in raw:
        head, _, annot = raw.partition(" - ")
    sid = head.strip().strip("`").strip()
    sid = re.split(r"\s", sid, maxsplit=1)[0].strip("`") if sid else sid
    if not sid:
        return None
    kind = _annot_value(annot, "kind")
    edge_class = _annot_value(annot, "edge_class")
    if kind or edge_class:
        return {"on": sid, "kind": kind or "ordering", "edge_class": edge_class or "ordering"}
    return sid


def _annot_value(annot: str, key: str) -> str | None:
    m = re.search(rf"{re.escape(key)}:\s*([\w.\-]+)", annot)
    return m.group(1) if m else None


def _parse_integration_check(items: list[str]) -> dict | list:
    """An ``integration_checks`` bullet is rendered as ``IC-id: assert (status: ...)``. Re-shape
    the FIRST such bullet into the object form ``{id, assert, status}`` the importer tolerates
    (the real JSON emit is a single object). Multiple bullets -> a list of objects."""
    out: list[dict] = []
    for raw in items:
        m = re.match(r"^\s*(?P<id>[\w.\-]+):\s*(?P<rest>.*)$", raw)
        if not m:
            out.append({"id": "", "assert": raw.strip(), "status": "UNVERIFIED"})
            continue
        rest = m.group("rest")
        status = "UNVERIFIED"
        sm = re.search(r"\(status:\s*(?P<st>.*?)\)\s*$", rest)
        if sm:
            status = sm.group("st").strip()
            rest = rest[:sm.start()].strip()
        out.append({"id": m.group("id"), "assert": rest.strip(), "status": status})
    if not out:
        return []
    return out[0] if len(out) == 1 else out


def _iter_step_blocks(lines: list[str]):
    """Yield (step_id, title, body_lines) for each ``### <step_id>`` block."""
    cur_sid: str | None = None
    cur_title = ""
    body: list[str] = []
    for line in lines:
        m = _STEP_HEADER.match(line)
        if m:
            if cur_sid is not None:
                yield cur_sid, cur_title, body
            cur_sid = m.group("sid")
            cur_title = (m.group("title") or "").strip()
            body = []
        elif cur_sid is not None:
            body.append(line)
    if cur_sid is not None:
        yield cur_sid, cur_title, body


def _parse_step_body(body: list[str]) -> dict:
    """Parse one step block's ``- **field:**`` lines (with sub-bullets) into a step dict."""
    fields: dict[str, list[str]] = {}
    inline: dict[str, str] = {}
    cur_field: str | None = None
    for line in body:
        fm = _FIELD_LINE.match(line)
        if fm:
            cur_field = fm.group("field")
            val = fm.group("val").strip()
            fields[cur_field] = []
            if val:
                inline[cur_field] = val
            continue
        sm = _SUBITEM.match(line)
        if sm and cur_field is not None:
            item = sm.group("item").strip()
            if item and not _is_none_value(item):
                fields[cur_field].append(item)

    step: dict = {}
    for field, items in fields.items():
        if not items and field in inline:
            items = _split_inline_list(inline[field]) if field in _LIST_FIELDS else [inline[field]]
        if field in _SCALAR_FIELDS:
            v = inline.get(field, items[0] if items else "")
            if not _is_none_value(v):
                step[field] = v.strip()
        elif field == "integration_checks":
            step["integration_checks"] = _parse_integration_check(items)
        elif field == "dependencies":
            step["dependencies"] = [dep for dep in (_clean_dep(d) for d in items) if dep]
        elif field in _LIST_FIELDS:
            step[field] = [i for i in items if not _is_none_value(i)]
        else:
            # unknown field: preserve as a string so no content is dropped
            step[field] = inline.get(field, "; ".join(items))
    return step


def _parse_gate_status(text: str) -> dict:
    """Map the ``## Coverage Verdict`` block (``- **decision:** FAIL`` / ``- **blocking:** true``)
    to a ``gate_status`` object. Default to a conservative non-PASS when absent so the executor's
    INV-17 gate fails safe rather than silently proceeding."""
    decision = None
    blocking = None
    reason = ""
    in_block = False
    for line in text.splitlines():
        if re.match(r"^##\s+Coverage Verdict", line, re.IGNORECASE):
            in_block = True
            continue
        if in_block and line.startswith("## "):
            break
        if in_block:
            m = _FIELD_LINE.match(line)
            if not m:
                continue
            f, v = m.group("field").lower(), m.group("val").strip()
            if f == "decision":
                decision = v
            elif f == "blocking":
                blocking = v.lower() in ("true", "yes", "1")
            elif f == "rationale":
                reason = v
    verdict = (decision or "UNKNOWN").upper().split()[0] if decision else "UNKNOWN"
    gate = "BLOCKING" if (blocking or verdict not in ("PASS",)) else "OPEN"
    return {"verdict": verdict, "gate": gate, "reason": reason}


def _parse_execution_order(text: str, valid: set[str]) -> list[str]:
    """The ``## Execution Order`` numbered list -> a flat ordered list of step_ids. Returned as a
    single build_order layer string (the importer parses step_ids out of layer strings)."""
    order: list[str] = []
    in_block = False
    for line in text.splitlines():
        if re.match(r"^##\s+Execution Order", line, re.IGNORECASE):
            in_block = True
            continue
        if in_block and line.startswith("## "):
            break
        if in_block:
            m = re.match(r"^\s*(?:\d+\.|-)\s+(?P<sid>[A-Za-z0-9][\w.\-]*)", line)
            if m and m.group("sid") in valid:
                order.append(m.group("sid"))
    return order


def normalize_plan_md(text: str) -> tuple[dict, list[str]]:
    """epiphany-plan Markdown -> execution-plan dict + lossy_fields[].

    Faithful path: when the Markdown carries step blocks + a verdict + an execution order, the
    result needs no lossy degradation. Records a lossy entry only for genuinely-missing structure
    (e.g. no execution order -> document-order build_order fallback)."""
    lines = text.splitlines()
    lossy: list[str] = []
    steps: list[dict] = []
    titles: dict[str, str] = {}
    for sid, title, body in _iter_step_blocks(lines):
        step = _parse_step_body(body)
        step["step_id"] = sid
        if title and "goal" not in step:
            step["goal"] = title
        titles[sid] = title
        steps.append(step)

    if not steps:
        raise ValueError("no '### <step_id>' step blocks found — not an epiphany-plan Markdown")

    valid = {s["step_id"] for s in steps}
    order = _parse_execution_order(text, valid)
    if order:
        build_order = [f"Execution order: {' -> '.join(order)}"]
    else:
        # document-order fallback (declared, visible policy)
        lossy.append("build_order (no '## Execution Order'; using document order)")
        build_order = [f"Document order: {' -> '.join(s['step_id'] for s in steps)}"]

    gate_status = _parse_gate_status(text)
    if gate_status["verdict"] == "UNKNOWN":
        lossy.append("gate_status (no '## Coverage Verdict'; defaulted to UNKNOWN/BLOCKING)")

    plan = {
        "plan_id": _scan_meta(text, "plan_id") or "md-plan",
        "title": (lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else "md-plan"),
        "source_spec": _scan_meta(text, "source_spec") or "",
        "consumers": [c.strip() for c in (_scan_meta(text, "consumers") or "").split(",") if c.strip()],
        "gate_status": gate_status,
        "blocking_defects": [],
        "structural_faults": [],
        "build_order": build_order,
        "steps": steps,
        "refinement_back_edges": [],
        "normalized_from": "epiphany-plan-markdown",
    }
    return plan, lossy


def _scan_meta(text: str, key: str) -> str | None:
    """Pull a ``> **key:** value`` or ``**key:** value`` token out of the header blockquote."""
    m = re.search(rf"\*\*{re.escape(key)}:\*\*\s*([^·\n]+)", text)
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------------
# brainstorming MD -> best-effort
# --------------------------------------------------------------------------
def normalize_brainstorming_md(text: str) -> tuple[dict, list[str]]:
    """Unstructured brainstorming Markdown -> best-effort execution-plan dict + lossy_fields[].

    Each ``#``/``##`` section becomes a step; per-step fields that brainstorming text never
    declares (actions/outputs/acceptance_criteria/dependencies) are emitted EMPTY and recorded in
    ``lossy_fields`` (degraded != authoritative). Zero declared dependencies -> document-order
    fallback. The result is honestly flagged so the executor can refuse to treat it as
    authoritative."""
    lines = text.splitlines()
    sections: list[tuple[int, str, str]] = []   # (heading-level, title, body)
    cur_level: int | None = None
    cur_title = None
    cur_body: list[str] = []
    for line in lines:
        hm = re.match(r"^(?P<h>#{1,3})\s+(?P<t>.+)$", line)
        if hm:
            if cur_title is not None:
                sections.append((cur_level or 1, cur_title, "\n".join(cur_body)))
            cur_level = len(hm.group("h"))
            cur_title = hm.group("t").strip()
            cur_body = []
        elif cur_title is not None:
            cur_body.append(line)
    if cur_title is not None:
        sections.append((cur_level or 1, cur_title, "\n".join(cur_body)))

    # A leading H1 with deeper headings after it is the DOCUMENT TITLE, not a step. Drop it so the
    # title is not mistaken for executable work (only when subordinate sections exist).
    if len(sections) > 1 and sections[0][0] == 1 and any(lvl > 1 for lvl, _, _ in sections[1:]):
        title_line = sections[0][1]
        sections = sections[1:]
    else:
        title_line = sections[0][1] if sections else "brainstorm"
    sections = [(t, b) for _lvl, t, b in sections]

    steps: list[dict] = []
    used_ids: set[str] = set()
    for i, (title, body) in enumerate(sections):
        base = "S-" + (re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:40] or f"sec-{i}")
        sid = base
        n = 1
        while sid in used_ids:           # keep step ids unique (importer rejects duplicates)
            n += 1
            sid = f"{base}-{n}"
        used_ids.add(sid)
        steps.append({
            "step_id": sid,
            "goal": title,
            "actions": [],                 # brainstorming declares none
            "inputs": [],
            "outputs": [],
            "dependencies": [],            # zero declared -> document-order fallback below
            "acceptance_criteria": [],     # INV-10: unverifiable -> executor will BLOCK
            "integration_checks": [],
            "traces_to": [],
            "_brainstorm_body": body.strip(),
        })
    if not steps:
        raise ValueError("no sections found in brainstorming Markdown")

    lossy = [f"{f} (brainstorming: not declared, emitted empty)"
             for f in ("actions", "outputs", "dependencies", "acceptance_criteria")]
    lossy.append("dependencies (zero declared; document-order fallback)")
    build_order = [f"Document order: {' -> '.join(s['step_id'] for s in steps)}"]

    plan = {
        "plan_id": "brainstorm-md",
        "title": title_line,
        "consumers": [],
        # degraded source is NOT execution-ready: gate it BLOCKING so the executor halts at INV-17
        # rather than running an unverifiable, dependency-less plan as authoritative.
        "gate_status": {"verdict": "FAIL", "gate": "BLOCKING",
                        "reason": "normalized from unstructured brainstorming Markdown (degraded, not authoritative)"},
        "blocking_defects": [{"id": "DEFECT-LOSSY", "type": "degraded_brainstorming_source",
                              "where": "all steps", "detail": "missing per-step fields; see lossy_fields"}],
        "structural_faults": [],
        "build_order": build_order,
        "steps": steps,
        "refinement_back_edges": [],
        "lossy_fields": lossy,
        "normalized_from": "brainstorming-markdown",
    }
    return plan, lossy
