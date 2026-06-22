"""Corpus enumeration + tuning/held-out partition (S-P6-corpus, PC-03, F-12).

Enumerates the reference corpus and assigns each plan to a **tuning** set (used by S-P1 /
S-P6-validate) or a DISJOINT **held-out** set (used by the S-P6-benchmark, which the executor's
authors did not tune against — F-12 rigor). gate-FAIL JSON runs are validated as **correct-halt**
(INV-17), not end-to-end. The partition is explicit + reproducible (no `Date`/random — runtime
forbids them; partition is by declared role).
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field

REAL_RUNS_DIR = "/home/myuser/docs/goatcs-output/epiphany-plan-runs"
MD_PLANS_DIR = "/home/myuser/projects/epiphany-plan"


@dataclass
class CorpusPlan:
    name: str
    path: str
    kind: str            # "json" | "md"
    role: str            # "tuning" | "held-out"
    disposition: str     # "end-to-end" | "correct-halt"
    gate_verdict: str | None = None


def _is_execution_plan(d: dict) -> bool:
    return isinstance(d, dict) and "steps" in d and "build_order" in d and "gate_status" in d


def enumerate_json_runs(runs_dir: str = REAL_RUNS_DIR) -> list[tuple[str, str, dict]]:
    out = []
    for p in sorted(glob.glob(os.path.join(runs_dir, "*", "*execution-plan.json"))):
        try:
            d = json.load(open(p))
        except (ValueError, OSError):
            continue
        if _is_execution_plan(d):
            out.append((os.path.basename(os.path.dirname(p)), p, d))
    return out


def enumerate_md_plans(md_dir: str = MD_PLANS_DIR) -> list[tuple[str, str]]:
    return [(os.path.basename(p), p) for p in sorted(glob.glob(os.path.join(md_dir, "*.md")))]


@dataclass
class CorpusPartition:
    tuning: list[CorpusPlan] = field(default_factory=list)
    held_out: list[CorpusPlan] = field(default_factory=list)

    @property
    def disjoint(self) -> bool:
        return not (set(p.name for p in self.tuning) & set(p.name for p in self.held_out))

    def summary(self) -> dict:
        return {
            "n_tuning": len(self.tuning), "n_held_out": len(self.held_out),
            "disjoint": self.disjoint,
            "correct_halt": [p.name for p in self.tuning + self.held_out
                             if p.disposition == "correct-halt"],
        }


def partition_corpus(*, held_out_names: set[str] | None = None,
                     runs_dir: str = REAL_RUNS_DIR, md_dir: str = MD_PLANS_DIR) -> CorpusPartition:
    """Partition the corpus. `held_out_names` (plan dir/file names) are reserved for the benchmark;
    everything else is tuning. gate-FAIL JSON runs get disposition `correct-halt` (INV-17)."""
    held_out_names = held_out_names or set()
    part = CorpusPartition()
    for name, path, d in enumerate_json_runs(runs_dir):
        verdict = (d.get("gate_status") or {}).get("verdict")
        disp = "correct-halt" if verdict and verdict != "PASS" else "end-to-end"
        role = "held-out" if name in held_out_names else "tuning"
        cp = CorpusPlan(name=name, path=path, kind="json", role=role,
                        disposition=disp, gate_verdict=verdict)
        (part.held_out if role == "held-out" else part.tuning).append(cp)
    for name, path in enumerate_md_plans(md_dir):
        role = "held-out" if name in held_out_names else "tuning"
        cp = CorpusPlan(name=name, path=path, kind="md", role=role, disposition="end-to-end")
        (part.held_out if role == "held-out" else part.tuning).append(cp)
    return part
