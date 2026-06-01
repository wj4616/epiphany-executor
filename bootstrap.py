"""Thin shim proving this package is harness-loadable (§4).

The runtime harness builds the Burr app generically; this exposes a
build(session_dir) entry that loads THIS package's graph.json.
"""
from __future__ import annotations
import os
from goatcs_harness import loader
from goatcs_harness.build import build_application
from goatcs_harness.persist import SessionPaths, make_persister


HERE = os.path.dirname(os.path.abspath(__file__))


def build(session_dir, *, seed=None):
    spec = loader.load(os.path.join(HERE, 'graph.json'))
    paths = SessionPaths(os.path.abspath(session_dir)).ensure()
    persister = make_persister(paths.db)
    return build_application(spec, persister, app_id=os.path.basename(session_dir),
                             partition_key=spec.skill_name, seed=seed or {})
