import json
from pathlib import Path

import pytest

from omniagent.eval_platform import (
    EvalDataset,
    EvalResult,
    EvalRun,
    field_f1,
    percentile,
    summarize,
)
from omniagent.quality_gates import compare, eval_passes

pytestmark = [pytest.mark.unit, pytest.mark.eval]


def make_run(**changes):
    result = EvalResult(
        case_id="negative-control",
        profile_id="hr",
        split="test",
        expected_outcome="answer",
        actual_outcome="answer",
        e2e_success=True,
        route_correct=True,
        actual_route="retrieve",
        latency_ms=10,
        cost_microusd=None,
        **changes,
    )
    return EvalRun(
        run_id="test",
        created_at="test",
        dataset_version="test",
        dataset_hash="fixed",
        variant="test",
        versions={},
        metrics=summarize([result]),
        safety_gates={
            "unauthorized_write_zero": not result.unauthorized_write,
            "kb_isolation_zero": not result.kb_isolation_violation,
            "attack_success_zero": not result.attack_success,
        },
        results=[result],
    )


@pytest.mark.parametrize(
    "failure", ["unauthorized_write", "kb_isolation_violation", "attack_success"]
)
def test_safety_failure_cannot_be_hidden_by_perfect_quality(failure):
    run = make_run(**{failure: True})
    assert run.metrics["e2e_success_rate"] == 1
    assert not eval_passes(run)


def test_unknown_cost_missing_denominator_and_field_f1_are_explicit():
    run = make_run()
    assert run.metrics["cost_microusd"] == "unknown"
    assert run.metrics["citation_validity"] is None
    assert field_f1({"sku": "P-100", "quantity": 1}, {"sku": "P-100", "quantity": 2}) == 0.5
    assert field_f1({}, {}) == 1 and field_f1({"value": 1}, {"value": "1"}) == 0
    assert percentile([0, 10, 20], 0.95) == 19


def test_frozen_dataset_balances_profiles_splits_and_has_versioned_attacks():
    dataset = EvalDataset.model_validate_json(
        Path("evals/v1/cases.json").read_text(encoding="utf-8")
    )
    assert len(dataset.cases) >= 60
    assert len({case.case_id for case in dataset.cases}) == len(dataset.cases)
    assert {case.profile_id for case in dataset.cases} == {"hr", "support", "sales"}
    assert sum(bool(case.attack_type) for case in dataset.cases) >= 12
    assert {case.split for case in dataset.cases} == {"dev", "test"}


def test_comparison_refuses_dataset_drift_and_produces_chart(tmp_path):
    run = make_run()
    baseline, candidate = tmp_path / "b.json", tmp_path / "c.json"
    baseline.write_text(run.model_dump_json(), encoding="utf-8")
    candidate.write_text(run.model_dump_json(), encoding="utf-8")
    compare(baseline, candidate, tmp_path / "comparison")
    assert (tmp_path / "comparison/comparison.svg").exists()
    data = json.loads(candidate.read_text())
    data["dataset_hash"] = "changed"
    candidate.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="same dataset"):
        compare(baseline, candidate, tmp_path / "invalid")
