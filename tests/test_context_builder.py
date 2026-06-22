"""S-P2-context IC-P2c: hold-all default; over-budget degrades; irreversible -> DEEP never
down-tiered; memory advisory-only."""
from epiphany_executor.context_builder import (
    ResidentMode,
    ThinkingTier,
    allocate_thinking_tier,
    apply_memory_priors,
    build_step_context,
    resident_context_mode,
)
from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.scheduler import build_dag


def _c(step_id, outputs=None, deps=None, criteria=("ok",)):
    return stamp_node_contract({"step_id": step_id, "outputs": list(outputs or []),
                                "dependencies": list(deps or []),
                                "acceptance_criteria": list(criteria)})


def test_hold_all_is_default_under_budget():
    assert resident_context_mode(100, 100, budget_chars=1000) == ResidentMode.HOLD_ALL


def test_degrades_to_tiered_then_stream_over_budget():
    # plan+ledger over 70% but plan alone under -> tiered
    assert resident_context_mode(600, 200, budget_chars=1000) == ResidentMode.TIERED_SUMMARY
    # plan alone over 70% -> windowed stream
    assert resident_context_mode(800, 100, budget_chars=1000) == ResidentMode.WINDOWED_STREAM


def test_irreversible_step_is_deep():
    c = _c("x", outputs=["https://deploy/prod"])
    tier, why = allocate_thinking_tier(c, reversibility="externally-irreversible")
    assert tier == ThinkingTier.DEEP
    assert any("never down-tiered" in w for w in why)


def test_unknown_effect_is_deep():
    c = _c("x", outputs=[])
    tier, _ = allocate_thinking_tier(c, reversibility="unknown")
    assert tier == ThinkingTier.DEEP


def test_high_fanout_hub_is_deep():
    c = _c("h", outputs=["src/h.py"])
    tier, _ = allocate_thinking_tier(c, fan_out=4, reversibility="local-mutating")
    assert tier == ThinkingTier.DEEP


def test_mechanical_leaf_is_minimal():
    c = _c("leaf", outputs=["src/leaf.py"], criteria=("ok",))
    tier, _ = allocate_thinking_tier(c, fan_out=0, reversibility="local-mutating")
    assert tier == ThinkingTier.MINIMAL


def test_memory_prior_only_raises_never_lowers():
    c = _c("x", outputs=["https://deploy"])
    tier, _ = allocate_thinking_tier(c, reversibility="externally-irreversible")  # DEEP
    lowered, note = apply_memory_priors(tier, {"suggested_tier": "minimal"})
    assert lowered == ThinkingTier.DEEP and note == []          # cannot lower below floor
    raised, note2 = apply_memory_priors(ThinkingTier.MINIMAL, {"suggested_tier": "deep"})
    assert raised == ThinkingTier.DEEP and note2                # may raise (advisory)


def test_empty_memory_is_noop():
    assert apply_memory_priors(ThinkingTier.STANDARD, None) == (ThinkingTier.STANDARD, [])
    assert apply_memory_priors(ThinkingTier.STANDARD, {}) == (ThinkingTier.STANDARD, [])


def test_look_behind_ahead_and_deltas():
    contracts = {"a": _c("a", outputs=["src/a.py"]),
                 "b": _c("b", outputs=["src/b.py"], deps=["a"]),
                 "c": _c("c", outputs=["src/c.py"], deps=["b"])}
    dag = build_dag(contracts)
    ctx = build_step_context(contracts, "b", dag, accepted={"a"},
                             ledger_deltas={"a": {"wrote": "src/a.py"}})
    assert ctx.look_behind == ["a"]
    assert ctx.look_ahead == ["c"]                              # downstream dependent (INV-11)
    assert ctx.predecessor_deltas == {"a": {"wrote": "src/a.py"}}
