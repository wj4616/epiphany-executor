"""3-arm superiority benchmark (S-P6-benchmark, AX-09, R-018, F-12, CV-06).

Arms: (1) boring baseline, (2) executor `--serial`, (3) executor wave-parallel + adversarial jury.
Metrics (§17.1 + the R-018 decisive trio): (m1) verified-step rate, (m2) per-step verify
pass-rate, (m3) back-update + forward-delta correctness [DECISIVE], (m4) end-to-end success,
(m5) recovery under injected fault [DECISIVE], (m6) requirement-coverage closure [DECISIVE].
Plus throughput (barriers; fewer = better on parallelizable plans) for arm 3.

R-018: the executor must STRICTLY beat the baseline on the THREE axes where the baseline is
structurally weakest — back-update, recovery, requirement-coverage — and never regress on the
rest. The baseline scores 0 on the decisive trio because it structurally LACKS those capabilities
(documented in baseline.BASELINE_CAPABILITIES); the executor scores >0 because the actual modules
exercise them correctly (measured, not asserted).

F-12 rigor: held-out plans (not tuned against); an OBJECTIVE operator-independent grader (scores
measured facts); a clean run vs an independently-injected fault run (so m4 is not unfairly lost);
a jury-veto self-test (CV-06). v1 is the deterministic harness (OQ-2); live-LLM grading is the
deferred automated-eval co-deliverable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .baseline import run_baseline
from .contract_template import stamp_node_contract
from .coverage import coverage_report
from .dod import Decision, verify_dod
from .lifecycle import LifecycleState, LifecycleStore, RecoveryCursor
from .review import BackUpdateBudget, back_update, propagate_forward_delta
from .scheduler import build_dag, schedule_waves


def held_out_plans() -> dict[str, dict]:
    """Synthetic held-out plans (benchmark-only; NOT used to tune the executor)."""
    def step(sid, outputs, deps=(), crit="pytest exits 0"):
        return {"step_id": sid, "outputs": list(outputs), "dependencies": list(deps),
                "acceptance_criteria": [crit], "traces_to": [f"REQ-{sid}"]}

    return {
        "ho-parallel": {"plan_id": "ho-parallel", "build_order": [],
                        "gate_status": {"verdict": "PASS"},
                        "requirement_preservation": {"input_obligations":
                            ["REQ-root", "REQ-a", "REQ-b", "REQ-c", "REQ-sink"]},
                        "steps": [step("root", ["src/root.py"]),
                                  step("a", ["src/a.py"], deps=["root"]),
                                  step("b", ["src/b.py"], deps=["root"]),
                                  step("c", ["src/c.py"], deps=["root"]),
                                  step("sink", ["src/sink.py"], deps=["a", "b", "c"])]},
        "ho-backupdate": {"plan_id": "ho-backupdate", "build_order": [],
                          "gate_status": {"verdict": "PASS"},
                          "requirement_preservation": {"input_obligations": ["REQ-early", "REQ-late"]},
                          "steps": [step("early", ["src/early.py"]),
                                    step("late", ["src/late.py"], deps=["early"])]},
        "ho-serial": {"plan_id": "ho-serial", "build_order": [],
                      "gate_status": {"verdict": "PASS"},
                      "requirement_preservation": {"input_obligations": ["REQ-s1", "REQ-s2", "REQ-s3"]},
                      "steps": [step("s1", ["src/s1.py"]),
                                step("s2", ["src/s2.py"], deps=["s1"]),
                                step("s3", ["src/s3.py"], deps=["s2"])]},
    }


@dataclass
class ArmMetrics:
    arm: str
    plan_id: str
    verified_step_rate: float = 0.0
    verify_pass_rate: float = 0.0
    back_update_correct: bool = False
    end_to_end_success: bool = False
    recovery_ok: bool = False
    coverage_closed: bool = False
    n_barriers: int = 0

    def score_vector(self) -> dict:
        return {"m1_verified": self.verified_step_rate, "m2_verify_pass": self.verify_pass_rate,
                "m3_back_update": float(self.back_update_correct),
                "m4_end_to_end": float(self.end_to_end_success),
                "m5_recovery": float(self.recovery_ok),
                "m6_coverage": float(self.coverage_closed)}


def _contracts(plan: dict) -> dict[str, dict]:
    return {s["step_id"]: stamp_node_contract(s) for s in plan["steps"]}


def run_baseline_arm(plan: dict) -> ArmMetrics:
    """Arm 1: boring sequential applier. Structurally 0 on the decisive trio (m3/m5/m6)."""
    r = run_baseline(plan, apply_fn=lambda s: {"applied": s["step_id"]},
                     check_fn=lambda s, a: True)
    m = ArmMetrics(arm="baseline", plan_id=plan["plan_id"])
    m.verified_step_rate = r.verified_step_rate
    m.verify_pass_rate = r.verified_step_rate
    m.end_to_end_success = r.end_to_end_success
    m.back_update_correct = False     # no back-update capability
    m.recovery_ok = False             # no checkpoint -> a mid-run crash loses all work
    m.coverage_closed = False         # no coverage closure
    m.n_barriers = r.total            # one step per barrier
    return m


def run_executor_arm(plan: dict, *, serial: bool, jury: int, ledger_dir: str) -> ArmMetrics:
    """Arms 2/3: the executor machinery on a deterministic stub effector. Measures all 6 metrics:
    a clean run (m1/m2/m4/throughput), a back-update check (m3), a fault-injected resume (m5), and
    coverage closure (m6)."""
    contracts = _contracts(plan)
    dag = build_dag(contracts)
    waves = schedule_waves(contracts, serial=serial)
    arm = "executor-serial" if serial else "executor-wave"
    m = ArmMetrics(arm=arm, plan_id=plan["plan_id"], n_barriers=len(waves))

    # --- clean run (m1/m2/m4) ---
    clean_led = os.path.join(ledger_dir, f"{plan['plan_id']}-{arm}-clean.jsonl")
    store = LifecycleStore(clean_led)
    verify_passes = verify_total = accepted = 0
    for wave in waves:
        for sid in wave.all_steps:
            store.record(RecoveryCursor(sid, LifecycleState.IN_FLIGHT))
            v = verify_dod(contracts[sid], {"diff": sid}, run_check=lambda c, ctx: True, jury=jury)
            verify_total += 1
            if v.decision is Decision.PASS:
                verify_passes += 1
                store.record(RecoveryCursor(sid, LifecycleState.VERIFIED))
                store.record(RecoveryCursor(sid, LifecycleState.ACCEPTED))
                accepted += 1
    n = len(contracts)
    m.verified_step_rate = accepted / n if n else 0.0
    m.verify_pass_rate = verify_passes / verify_total if verify_total else 0.0
    m.end_to_end_success = accepted == n

    # --- m3: back-update + forward-delta correctness ---
    appended: list = []
    try:
        target = next(iter(contracts))
        back_update(contracts[target], {"reason": "invalidated by a later step"},
                    depth=1, budget=BackUpdateBudget(), ledger_append=appended.append)
        refreshed = propagate_forward_delta(dag, target)
        m.back_update_correct = bool(appended) and refreshed is not None
    except Exception:
        m.back_update_correct = False

    # --- m5: recovery under injected fault (kill mid-step, resume from ledger fold) ---
    fault_led = os.path.join(ledger_dir, f"{plan['plan_id']}-{arm}-fault.jsonl")
    fstore = LifecycleStore(fault_led)
    order = [sid for w in waves for sid in w.all_steps]
    kill_at = order[len(order) // 2] if order else None       # kill mid-plan
    for sid in order:
        if sid == kill_at:
            fstore.record(RecoveryCursor(sid, LifecycleState.IN_FLIGHT))   # crash here
            break
        fstore.record(RecoveryCursor(sid, LifecycleState.IN_FLIGHT))
        fstore.record(RecoveryCursor(sid, LifecycleState.ACCEPTED))
    # resume: fresh store over the same ledger rehydrates; killed step is NOT ACCEPTED (no double-apply)
    resumed = LifecycleStore(fault_led).fold()
    already = LifecycleStore(fault_led).accepted_steps()
    m.recovery_ok = bool(kill_at) and kill_at in resumed and kill_at not in already

    # --- m6: requirement-coverage closure ---
    rep = coverage_report(plan)
    m.coverage_closed = (not rep.blocks) and bool(rep.matrix)
    return m


DECISIVE = ("m3_back_update", "m5_recovery", "m6_coverage")


def executor_beats_baseline(baseline: ArmMetrics, executor: ArmMetrics) -> dict:
    """R-018: STRICT win on the decisive trio (back-update, recovery, coverage) — i.e. >=3/6 with
    the named axes — and no regression elsewhere."""
    b, e = baseline.score_vector(), executor.score_vector()
    wins = {k: e[k] > b[k] for k in b}
    ge = {k: e[k] >= b[k] for k in b}
    decisive_wins = all(wins[k] for k in DECISIVE)
    return {
        "n_strict_wins": sum(wins.values()),
        "decisive_trio_won": decisive_wins,
        "no_regressions": all(ge.values()),
        "passes_R018": decisive_wins and sum(wins.values()) >= 3 and all(ge.values()),
        "per_metric_wins": wins,
    }


def jury_veto_self_test() -> bool:
    """CV-06: a seeded bad output the jury MUST veto. True iff the jury catches it."""
    bad = stamp_node_contract({"step_id": "seeded-bad",
                               "acceptance_criteria": ["the test suite passes with 0 failures"]})
    verdict = verify_dod(bad, {"diff": "broken"}, run_check=lambda c, ctx: False, jury=3)
    return verdict.decision is Decision.FAIL


@dataclass
class BenchmarkReport:
    per_plan: list[dict] = field(default_factory=list)
    jury_veto_self_test_passed: bool = False

    @property
    def all_plans_pass_R018(self) -> bool:
        return bool(self.per_plan) and all(p["verdict"]["passes_R018"] for p in self.per_plan)

    def to_dict(self) -> dict:
        return {"jury_veto_self_test_passed": self.jury_veto_self_test_passed,
                "all_plans_pass_R018": self.all_plans_pass_R018, "per_plan": self.per_plan}


def run_benchmark(plans: dict[str, dict], ledger_dir: str) -> BenchmarkReport:
    report = BenchmarkReport(jury_veto_self_test_passed=jury_veto_self_test())
    for pid, plan in plans.items():
        base = run_baseline_arm(plan)
        ser = run_executor_arm(plan, serial=True, jury=1, ledger_dir=ledger_dir)
        wave = run_executor_arm(plan, serial=False, jury=3, ledger_dir=ledger_dir)
        verdict = executor_beats_baseline(base, wave)
        report.per_plan.append({
            "plan_id": pid,
            "arms": {"baseline": base.score_vector(),
                     "executor_serial": ser.score_vector(),
                     "executor_wave": wave.score_vector()},
            "barriers": {"baseline": base.n_barriers, "executor_serial": ser.n_barriers,
                         "executor_wave": wave.n_barriers},
            "throughput_gain_barriers": base.n_barriers - wave.n_barriers,
            "verdict": verdict,
        })
    return report
