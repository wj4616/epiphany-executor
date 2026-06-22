"""S-P3-effector-fanout IC-P3f: cohort runs in isolated worktrees; background action rejoins at
the barrier; no cross-worktree race; results are STAGED (uncommitted) at the barrier (CV-01)."""
from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.effector import _InMemoryWorktrees, dispatch_wave
from epiphany_executor.scheduler import Wave


def _c(step_id, outputs=None):
    return stamp_node_contract({"step_id": step_id, "acceptance_criteria": ["ok"],
                                "outputs": list(outputs or [f"src/{step_id}.py"])})


def test_cohort_runs_in_distinct_worktrees():
    contracts = {"a": _c("a"), "b": _c("b")}
    wt = _InMemoryWorktrees()
    wave = Wave(index=0, parallel=["a", "b"])
    res = dispatch_wave(wave, contracts, dispatch_fn=lambda s, c, w: {"wt": w}, worktrees=wt)
    paths = [r.worktree for r in res.results.values()]
    assert len(paths) == len(set(paths)) == 2          # distinct worktree per step (no race)
    assert set(wt.created) == set(paths)


def test_results_staged_not_committed():
    contracts = {"a": _c("a")}
    res = dispatch_wave(Wave(index=0, serial=["a"]), contracts,
                        dispatch_fn=lambda s, c, w: {"edit": 1})
    assert res.any_committed is False                  # barrier stages, never commits (CV-01)
    assert res.results["a"].artifacts == {"edit": 1}


def test_background_action_joins_at_barrier():
    contracts = {"build": _c("build")}

    def dispatch(s, c, w):
        return {"launched": True}

    def join(step_id):
        return {"build_log": "ok", "joined": True}

    res = dispatch_wave(Wave(index=0, serial=["build"]), contracts,
                        dispatch_fn=dispatch, is_background=lambda s, c: True, join_fn=join)
    r = res.results["build"]
    assert r.background is True and r.joined is True
    assert r.artifacts.get("build_log") == "ok"        # rejoined result collected at barrier


def test_dispatch_error_is_captured_not_raised():
    contracts = {"boom": _c("boom")}

    def bad(s, c, w):
        raise RuntimeError("effector blew up")

    res = dispatch_wave(Wave(index=0, serial=["boom"]), contracts, dispatch_fn=bad)
    assert res.all_ok is False
    assert "effector blew up" in res.results["boom"].error


def test_parallel_then_serial_ordering():
    contracts = {"p1": _c("p1"), "p2": _c("p2"), "s1": _c("s1")}
    order = []
    dispatch_wave(Wave(index=0, parallel=["p1", "p2"], serial=["s1"]), contracts,
                  dispatch_fn=lambda s, c, w: order.append(s) or {})
    assert order[-1] == "s1"                            # serial residue runs after the cohort
