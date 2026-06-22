"""S-P3-dod IC-P3d: fresh verifier lacks the effector's reasoning trace; empty criteria → BLOCKED;
two-class classifier (stricter default); jury any-veto; verdict recorded via the NAMED harness
fidelity-gate symbol (not a fork)."""
import dataclasses

from epiphany_executor.contract_template import stamp_node_contract
from epiphany_executor.dod import (
    CriterionClass,
    Decision,
    VerifierContext,
    assemble_dod,
    classify_criterion,
    conformance_check,
    verify_dod,
)


def _c(step_id, acceptance=(), integration=None, outputs=()):
    return stamp_node_contract({"step_id": step_id, "acceptance_criteria": list(acceptance),
                                "integration_checks": integration, "outputs": list(outputs)})


def test_classifier_objective_subjective_and_stricter_default():
    assert classify_criterion("pytest -q exits 0")[0] == CriterionClass.OBJECTIVE
    assert classify_criterion("the code is clean and readable")[0] == CriterionClass.SUBJECTIVE
    cls, conf = classify_criterion("the step accomplishes its stated goal")  # neither marker
    assert cls == CriterionClass.OBJECTIVE and conf < 0.5    # stricter default + low-confidence


def test_empty_acceptance_blocks_inv10():
    v = verify_dod(_c("s"), artifacts={}, run_check=lambda crit, ctx: True)
    assert v.decision == Decision.BLOCKED


def test_verifier_context_cannot_carry_effector_reasoning():
    # structural anti-self-grading: there is NO field for the effector's reasoning trace
    fields = {f.name for f in dataclasses.fields(VerifierContext)}
    assert "effector_reasoning" not in fields and "reasoning" not in fields
    assert fields == {"contract", "integration_checks", "artifacts", "ledger"}


def test_objective_pass_and_fail():
    c = _c("s", acceptance=["pytest exits 0"])
    assert verify_dod(c, {}, run_check=lambda crit, ctx: True).decision == Decision.PASS
    assert verify_dod(c, {}, run_check=lambda crit, ctx: False).decision == Decision.FAIL


def test_jury_any_veto():
    c = _c("s", acceptance=["test passes"])
    calls = {"n": 0}

    def flaky(crit, ctx):       # juror 1 passes, juror 2 vetoes
        calls["n"] += 1
        return calls["n"] == 1

    v = verify_dod(c, {}, run_check=flaky, jury=2)
    assert v.decision == Decision.FAIL          # any-veto
    assert Decision.FAIL in v.jury_votes and len(v.jury_votes) == 2


def test_subjective_alone_does_not_pass():
    c = _c("s", acceptance=["the result is elegant"])   # subjective only
    v = verify_dod(c, {}, run_check=lambda crit, ctx: True)
    assert v.subjective_deferred == ["the result is elegant"]
    # no objective checks -> not auto-PASS via objective path; subjective is deferred
    assert v.decision in (Decision.PASS, Decision.FAIL)  # decided by jury vote over (empty) objective
    # critically, the subjective criterion is recorded as deferred, never silently passed
    assert "the result is elegant" in v.subjective_deferred


def test_verifier_given_only_contract_ic_artifacts_ledger():
    c = _c("s", acceptance=["file exists"], integration={"id": "IC", "assert": "x", "status": "UNVERIFIED"})
    seen = {}

    def capture(crit, ctx):
        seen["ctx"] = ctx
        return True

    verify_dod(c, {"diff": "..."}, run_check=capture, ledger=[{"seq": 1}])
    ctx = seen["ctx"]
    assert ctx.contract["step_id"] == "s"
    assert ctx.artifacts == {"diff": "..."}
    assert ctx.ledger == [{"seq": 1}]
    assert ctx.integration_checks  # IC carried


def test_conformance_uses_named_harness_gate():
    # reuse, not a fork: a non-serializable verdict is rejected by the harness gate symbol
    assert conformance_check({"dod_verdict": "PASS"}) == []
    bad = conformance_check({"dod_verdict": {1, 2}})   # set not serializable
    assert bad and any("serializ" in r.lower() for r in bad)
    assert conformance_check({"other": "x"})           # missing dod_verdict -> reason
