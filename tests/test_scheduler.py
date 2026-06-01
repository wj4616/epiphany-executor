"""S-P2-scheduler IC-P2s: static-footprint conflict graph; output-overlap/irreversible never
share a cohort; unprovable-disjointness -> serial; fan-out budget caps + degrades; cycle
pre-flight excludes back-edges; --serial = width-1."""
import pytest

from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.scheduler import (
    FanoutBudget,
    SchedulerError,
    build_dag,
    detect_cycle,
    partition_cohort,
    schedule_summary,
    schedule_waves,
    static_effect_class,
    topo_layers,
)


def _c(step_id, outputs=None, deps=None, criteria=("ok",)):
    return stamp_node_contract({
        "step_id": step_id,
        "outputs": list(outputs or []),
        "dependencies": list(deps or []),
        "acceptance_criteria": list(criteria),
    })


def test_static_effect_class():
    assert static_effect_class(_c("a", outputs=["src/a.py"])) == "local-mutating"
    assert static_effect_class(_c("b", outputs=[])) == "unknown"          # undeclared -> conflicts-all
    assert static_effect_class(_c("c", outputs=["https://api/deploy"])) == "externally-irreversible"
    assert static_effect_class(_c("d", outputs=["publish to registry"])) == "externally-irreversible"


def test_disjoint_local_steps_share_a_cohort():
    contracts = {"a": _c("a", outputs=["src/a.py"]), "b": _c("b", outputs=["src/b.py"])}
    waves = schedule_waves(contracts)
    assert len(waves) == 1
    assert set(waves[0].parallel) == {"a", "b"}  # disjoint, local, independent -> parallel


def test_output_overlap_forces_serial():
    contracts = {"a": _c("a", outputs=["src/shared.py"]),
                 "b": _c("b", outputs=["src/shared.py"])}  # WRITE-WRITE conflict
    par, ser = partition_cohort(["a", "b"], contracts, FanoutBudget())
    assert par == []          # cannot share a cohort
    assert set(ser) == {"a", "b"}


def test_irreversible_never_in_cohort():
    contracts = {"a": _c("a", outputs=["src/a.py"]),
                 "b": _c("b", outputs=["https://deploy/prod"])}  # externally-irreversible
    par, ser = partition_cohort(["a", "b"], contracts, FanoutBudget())
    assert "b" in ser and "b" not in par


def test_undeclared_outputs_force_serial():
    contracts = {"a": _c("a", outputs=[]), "b": _c("b", outputs=[])}  # conflicts-with-all
    par, ser = partition_cohort(["a", "b"], contracts, FanoutBudget())
    assert par == [] and set(ser) == {"a", "b"}


def test_fanout_budget_caps_and_degrades():
    contracts = {f"s{i}": _c(f"s{i}", outputs=[f"src/{i}.py"]) for i in range(5)}
    budget = FanoutBudget(max_concurrent_effectors=2)
    par, ser = partition_cohort(list(contracts), contracts, budget)
    assert len(par) == 2          # capped
    assert len(ser) == 3          # overflow degraded to serial


def test_serial_flag_forces_width_1():
    contracts = {"a": _c("a", outputs=["src/a.py"]), "b": _c("b", outputs=["src/b.py"])}
    waves = schedule_waves(contracts, serial=True)
    assert all(w.width == 0 for w in waves)
    assert sum(len(w.serial) for w in waves) == 2


def test_dependency_layers_serialize():
    contracts = {"a": _c("a", outputs=["src/a.py"]),
                 "b": _c("b", outputs=["src/b.py"], deps=["a"])}
    waves = schedule_waves(contracts)
    assert len(waves) == 2                      # b depends on a -> two layers
    assert waves[0].all_steps == ["a"]
    assert waves[1].all_steps == ["b"]


def test_single_eligible_step_is_reported_serial_not_parallel():
    contracts = {"a": _c("a", outputs=["src/a.py"])}
    waves = schedule_waves(contracts)
    assert waves[0].width == 0 and waves[0].serial == ["a"]  # width-1 cohort == serial step


def test_cycle_preflight_raises():
    contracts = {"a": _c("a", deps=["b"]), "b": _c("b", deps=["a"])}
    dag = build_dag(contracts)
    assert detect_cycle(dag)                    # cycle found
    with pytest.raises(SchedulerError):
        topo_layers(dag)


def test_summary_counts():
    contracts = {"a": _c("a", outputs=["src/a.py"]), "b": _c("b", outputs=["src/b.py"]),
                 "c": _c("c", outputs=["src/c.py"], deps=["a", "b"])}
    waves = schedule_waves(contracts)
    s = schedule_summary(waves)
    assert s["n_waves"] == 2 and s["max_cohort_width"] == 2
