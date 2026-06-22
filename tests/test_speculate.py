"""S-P2-speculate IC-P2sp: speculation writes no ledger entry and fires no real irreversible
effect; predictions refine the cohort."""
from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.scheduler import FanoutBudget
from epiphany_executor.speculate import refine_cohort, speculate_antichain


def _c(step_id, outputs=None):
    return stamp_node_contract({"step_id": step_id, "outputs": list(outputs or []),
                                "acceptance_criteria": ["ok"]})


def test_speculation_never_commits_ledger():
    contracts = {"a": _c("a", ["src/a.py"]), "b": _c("b", ["src/b.py"])}

    def dry(sid, c):
        return {"predicted_outputs": [f"src/{sid}.py"], "effort": 1.0}

    res = speculate_antichain(["a", "b"], contracts, dry)
    assert res.wrote_ledger is False
    assert all(p.committed_ledger is False for p in res.predictions.values())


def test_a_committing_dry_run_is_rejected_not_trusted():
    contracts = {"a": _c("a", ["src/a.py"]), "b": _c("b", ["src/b.py"])}

    def bad(sid, c):
        return {"predicted_outputs": ["x"], "committed_ledger": True}  # violates IC-P2sp

    res = speculate_antichain(["a", "b"], contracts, bad)
    # the violating prediction is recorded as an error, NOT trusted, and no ledger flag survives
    assert res.wrote_ledger is False
    assert all(p.error for p in res.predictions.values())


def test_below_threshold_skips_speculation():
    contracts = {"a": _c("a", ["src/a.py"])}
    res = speculate_antichain(["a"], contracts, lambda s, c: {}, FanoutBudget(speculate_threshold=2))
    assert res.predictions == {}


def test_predicted_conflict_refines_cohort():
    contracts = {"a": _c("a", ["src/a.py"]), "b": _c("b", ["src/b.py"])}

    # the dry-run reveals BOTH actually touch the same file (undeclared by the static footprint)
    def dry(sid, c):
        return {"predicted_outputs": ["src/SHARED.py"]}

    res = speculate_antichain(["a", "b"], contracts, dry)
    assert ("a", "b") in res.predicted_conflicts
    refined, demoted = refine_cohort(["a", "b"], res)
    assert refined == ["a"] and demoted == ["b"]   # later member demoted to serial residue


def test_irreversible_stub_flag_propagates():
    contracts = {"a": _c("a", ["src/a.py"]), "b": _c("b", ["src/b.py"])}

    def dry(sid, c):
        return {"predicted_outputs": [f"src/{sid}.py"], "stubbed_irreversible": sid == "b"}

    res = speculate_antichain(["a", "b"], contracts, dry)
    assert res.predictions["b"].stubbed_irreversible is True
    assert res.predictions["a"].stubbed_irreversible is False
