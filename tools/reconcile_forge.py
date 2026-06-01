#!/usr/bin/env python3
"""Non-clobbering reconcile of a forge staging dir into the live working tree (PC-08, IC-P0).

forge is non-deterministic and the S-P8->S-P0 back-edge re-forges; neither must ever overwrite
hand-authored work (S-P1..S-P7 modules/code). Rule: copy a staged file into the live tree ONLY
if it does not already exist there. Existing files are PRESERVED verbatim. New skeleton files
are ADDED. Nothing is deleted. This guarantees "re-emit loses zero hand-authored files".

Usage: reconcile_forge.py <staging_dir> <live_root>
Exit 0 always (reconcile is additive); prints an added/preserved manifest as JSON.
"""
import json
import os
import shutil
import sys


def reconcile(staging: str, live: str) -> dict:
    added, preserved = [], []
    for root, _dirs, files in os.walk(staging):
        for fn in files:
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, staging)
            dst = os.path.join(live, rel)
            if os.path.exists(dst):
                preserved.append(rel)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)  # same-filesystem copy (avoids ecryptfs EXDEV from /tmp)
            added.append(rel)
    return {"added": sorted(added), "preserved": sorted(preserved),
            "n_added": len(added), "n_preserved": len(preserved)}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: reconcile_forge.py <staging_dir> <live_root>", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(reconcile(sys.argv[1], sys.argv[2]), indent=2))
