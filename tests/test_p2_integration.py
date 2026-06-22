"""P2 integration: the scheduler + context builder run over a REAL compiled GraphSpec (the
goatcs-v3 run, 82 steps) loaded through the harness epiphany-plan importer."""
import glob

import pytest

from epiphany_executor.context_builder import build_step_context
from epiphany_executor.scheduler import (
    build_dag,
    extract_contracts,
    schedule_summary,
    schedule_waves,
)

load = pytest.importorskip("goatcs_harness.loader").load

GOATCS_V3 = glob.glob("/home/myuser/docs/goatcs-output/epiphany-plan-runs/"
                      "2026-05-31-goatcs-v3-build-plan/*execution-plan.json")


@pytest.mark.skipif(not GOATCS_V3, reason="real run fixture not present")
def test_schedule_real_goatcs_v3_run():
    spec = load(GOATCS_V3[0])
    contracts = extract_contracts(spec)
    assert len(contracts) == 82
    waves = schedule_waves(contracts, build_order=spec.raw.get("build_order"))
    s = schedule_summary(waves)
    # every step appears exactly once across all waves (no drop, no duplication)
    scheduled = [sid for w in waves for sid in w.all_steps]
    assert sorted(scheduled) == sorted(contracts)
    assert s["n_waves"] >= 1
    # serial fallback schedules the same step set
    serial_waves = schedule_waves(contracts, build_order=spec.raw.get("build_order"), serial=True)
    serial_ids = [sid for w in serial_waves for sid in w.all_steps]
    assert sorted(serial_ids) == sorted(contracts)


@pytest.mark.skipif(not GOATCS_V3, reason="real run fixture not present")
def test_build_context_on_real_run_step():
    spec = load(GOATCS_V3[0])
    contracts = extract_contracts(spec)
    dag = build_dag(contracts, build_order=spec.raw.get("build_order"))
    sid = next(iter(contracts))
    ctx = build_step_context(contracts, sid, dag)
    assert ctx.step_id == sid
    assert ctx.thinking_tier is not None
