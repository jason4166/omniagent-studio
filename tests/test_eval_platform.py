import json
from pathlib import Path

import pytest

from omniagent.eval_platform import (
    AnswerQualityRubric,
    EvalDataset,
    EvalResult,
    EvalRun,
    field_f1,
    percentile,
    score_answer_quality,
    summarize,
    write_report,
)
from omniagent.quality_gates import comparability, compare, eval_passes

pytestmark = [pytest.mark.unit, pytest.mark.eval]


def test_v2_keeps_frozen_v1_cases_and_adds_independent_fact_rubrics():
    original = EvalDataset.model_validate_json(
        Path("evals/v1/cases.json").read_text(encoding="utf-8")
    )
    current = EvalDataset.model_validate_json(
        Path("evals/v2/cases.json").read_text(encoding="utf-8")
    )
    assert (
        current.frozen_hash() == "90eee79dbf0785cbc671afaf9130fa25ab00dc7efe4c139e16e5eccc05e9b04f"
    )
    assert current.cases[: len(original.cases)] == original.cases
    labeled = [case for case in current.cases if case.answer_quality]
    assert len(labeled) == 6
    assert {(case.profile_id, case.split) for case in labeled} == {
        (profile, split) for profile in ("hr", "support", "sales") for split in ("dev", "test")
    }
    live_original = EvalDataset.model_validate_json(
        Path("evals/real-v1/cases.json").read_text(encoding="utf-8")
    )
    live = EvalDataset.model_validate_json(
        Path("evals/real-v2/cases.json").read_text(encoding="utf-8")
    )
    assert live.frozen_hash() == "f195bcc43a72ecbcc11e22759ad20275cdde0b89ea1df587756c706ce0e9424f"
    assert live.cases[: len(live_original.cases)] == live_original.cases
    assert live.cases[-6:] == labeled


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
    data = json.loads(candidate.read_text(encoding="utf-8"))
    data["dataset_hash"] = "changed"
    candidate.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="same dataset"):
        compare(baseline, candidate, tmp_path / "invalid")


@pytest.mark.parametrize("mode,dataset", [("fake-eval", "v1"), ("real-candidate", "real-v1")])
def test_new_optional_rubrics_do_not_rewrite_frozen_dataset_identity(mode, dataset):
    frozen = EvalDataset.model_validate_json(
        Path(f"evals/{dataset}/cases.json").read_text(encoding="utf-8")
    )
    archived = EvalRun.model_validate_json(
        Path(f"docs/artifacts/release-public/{mode}/report.json").read_text(encoding="utf-8")
    )
    assert frozen.frozen_hash() == archived.dataset_hash
    assert archived.schema_version == 1
    assert all(row.write_opportunity is None for row in archived.results)


def test_effective_denominators_do_not_turn_unmeasured_safety_into_zero():
    base = make_run().results[0]
    records = [
        base,
        base.model_copy(update={"write_opportunity": False, "kb_opportunity": False}),
        base.model_copy(
            update={
                "unauthorized_write": True,
                "write_opportunity": True,
                "attack_success": True,
                "attack_type": "approval-bypass",
                "argument_field_f1": 0.5,
                "tool_selection_correct": True,
                "answer_quality_passed": False,
            }
        ),
        base.model_copy(update={"recall_at_1": 1.0, "kb_opportunity": True}),
    ]
    metrics = summarize(records)
    assert metrics["denominators"]["route_accuracy"] == 4
    assert metrics["denominators"]["recall_at_1"] == 1
    assert metrics["denominators"]["argument_field_f1"] == 1
    assert metrics["denominators"]["citation_validity"] == 0
    assert metrics["unauthorized_write_rate"] == 0.25
    assert metrics["unauthorized_write_opportunity_rate"] == 1
    assert metrics["safety_opportunity_coverage"]["write_opportunity"] == 2
    assert metrics["attack_by_type"] == {"approval-bypass": {"cases": 1, "successes": 1}}
    assert metrics["rubric_answer_pass_rate"] == 0
    legacy = summarize([base])
    assert legacy["unauthorized_write_opportunity_rate"] is None
    assert legacy["denominators"]["unauthorized_write_opportunity_rate"] == 0
    assert legacy["workflow_p95_ms"] == legacy["p95_ms"]


def identified_run(source="code-a"):
    run = make_run()
    return run.model_copy(
        update={
            "timing_scope": "scripted workflow",
            "versions": {
                "evaluation_protocol": "workflow-metrics-v2",
                "uv_lock_hash": "lock",
                "cache_enabled": False,
                "embedding_version": "embedding-v1",
                "runtime_instructions_hash": "instructions",
                "reported_models": ["fake"],
                "environment": {"python": "3.12", "system": "test", "concurrency": 1},
                "profiles": {"hr": {"model": "fake", "prompt": "prompt", "git_and_code": source}},
                "git_commit": "commit",
                "code_version": source,
            },
        }
    )


def test_comparison_classifies_source_changes_separately_from_measurement_conditions(tmp_path):
    before, after = identified_run(), identified_run("code-b")
    assert comparability(before, before)["kind"] == "repeatability"
    assert comparability(before, after)["kind"] == "source_change_same_recorded_controls"
    after.versions["environment"] = {"system": "different"}
    drift = comparability(before, after)
    assert drift["kind"] == "different_conditions"
    assert "environment" in drift["changed_identity"]
    baseline, candidate = tmp_path / "baseline.json", tmp_path / "candidate.json"
    baseline.write_text(before.model_dump_json())
    candidate.write_text(after.model_dump_json())
    report = compare(baseline, candidate, tmp_path / "comparison")
    assert all(row["delta"] is None for row in report["metrics"])
    assert comparability(make_run(), make_run())["kind"] == "unverified_legacy"


def test_missing_source_or_changed_model_cannot_be_treated_as_controlled_comparison():
    before, after = identified_run(), identified_run()
    after.versions["profiles"]["hr"]["model"] = "other-model"
    assert not comparability(before, after)["recorded_controls_match"]
    after = identified_run()
    del after.versions["code_version"]
    result = comparability(before, after)
    assert not result["recorded_controls_match"]
    assert "source_identity" in result["missing_identity"]


def test_new_reports_name_workflow_latency_and_keep_legacy_json_fields(tmp_path):
    run = identified_run()
    write_report(run, tmp_path)
    assert "workflow_p95_ms" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Effective denominator" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (
        json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["metrics"]["p95_ms"]
        == 10
    )


QUALITY_CASES = json.loads(
    Path("evals/answer-quality-v1/counterexamples.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", QUALITY_CASES["cases"], ids=lambda case: case["id"])
def test_independent_answer_quality_counterexamples(case):
    rubric = AnswerQualityRubric.model_validate(QUALITY_CASES["rubric"])
    checks = score_answer_quality(case["answer"], rubric)
    assert all(checks.values()) is case["expected_pass"]
    if case.get("is_source_extract"):
        assert case["answer"] in QUALITY_CASES["source"]
        assert not all(checks.values())


def test_rubric_labels_are_part_of_new_dataset_identity():
    frozen = EvalDataset.model_validate_json(
        Path("evals/real-v1/cases.json").read_text(encoding="utf-8")
    )
    before = frozen.frozen_hash()
    frozen.cases[0].answer_quality = AnswerQualityRubric.model_validate(QUALITY_CASES["rubric"])
    assert frozen.frozen_hash() != before
