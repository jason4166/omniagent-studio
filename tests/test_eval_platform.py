import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from omniagent.eval_platform import (
    AnswerQualityRubric,
    EvalCase,
    EvalDataset,
    EvalResult,
    EvalRun,
    field_f1,
    percentile,
    score_answer_quality,
    score_case,
    summarize,
    write_report,
)
from omniagent.quality_gates import comparability, compare, eval_passes

pytestmark = [pytest.mark.unit, pytest.mark.eval]


def test_v3_changes_only_hr_greeting_and_adds_six_public_conversation_cases():
    old = json.loads(Path("evals/v2/cases.json").read_text(encoding="utf-8"))
    new = json.loads(Path("evals/v3/cases.json").read_text(encoding="utf-8"))
    dataset = EvalDataset.model_validate(new)
    assert (
        dataset.frozen_hash() == "d5e82673cd56edcdc17e52cdbf2e4dbffde3da8cb3e45e55f522360c6e040422"
    )
    assert len(dataset.cases) == 78
    assert len({case.case_id for case in dataset.cases}) == 78
    assert {
        split: sum(case.split == split for case in dataset.cases) for split in ("dev", "test")
    } == {
        "dev": 39,
        "test": 39,
    }
    for original, inherited in zip(old["cases"], new["cases"][:72], strict=True):
        if original["case_id"] == "hr-13":
            assert original["expected_route"] == "retrieve"
            assert original["expected_outcome"] == "abstain"
            expected = dict(original, expected_route="direct", expected_outcome="conversation")
            rubric = inherited["answer_quality"]
            assert rubric["required_facts"]["chinese_greeting"]
            assert inherited == dict(expected, answer_quality=rubric)
        else:
            assert inherited == original
    meta = [case for case in dataset.cases if case.expected_outcome == "conversation"]
    assert len(meta) == 7
    assert all(case.expected_route == "direct" and case.answer_quality for case in meta)
    assert {(case.profile_id, case.role) for case in meta if case.split == "dev"} == {
        ("hr", "member"),
        ("support", "member"),
        ("sales", "member"),
        ("sales", "viewer"),
    }
    assert {case.profile_id for case in meta if case.split == "test"} == {"hr", "support", "sales"}


def test_real_v3_preserves_all_thirty_business_cases_and_adds_seven_meta_cases():
    old = json.loads(Path("evals/real-v2/cases.json").read_text(encoding="utf-8"))
    new = json.loads(Path("evals/real-v3/cases.json").read_text(encoding="utf-8"))
    dataset = EvalDataset.model_validate(new)
    assert (
        dataset.frozen_hash() == "3a9d1d274658acc5e5aa0cab55efbd1856b2db891a21359f3cbebb3234125306"
    )
    assert len(dataset.cases) == 37
    assert len({case.case_id for case in dataset.cases}) == 37
    assert new["cases"][:30] == old["cases"]
    assert all(case.expected_outcome == "conversation" for case in dataset.cases[30:])
    fake = EvalDataset.model_validate_json(Path("evals/v3/cases.json").read_text(encoding="utf-8"))
    expected = {
        (case.profile_id, case.split, case.role): (case.query, case.answer_quality)
        for case in fake.cases
        if case.expected_outcome == "conversation"
    }
    assert {
        (case.profile_id, case.split, case.role): (case.query, case.answer_quality)
        for case in dataset.cases[30:]
    } == expected


def score_public_reply(expected, route="direct", response_kind=None, status="succeeded"):
    case = EvalCase(
        case_id="public-reply",
        split="test",
        profile_id="hr",
        query="你好",
        expected_route=route,
        expected_outcome=expected,
    )
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(data={"route": route})
    db.scalars.return_value = []
    db.get.return_value = None
    store = MagicMock()
    store.profile.return_value = SimpleNamespace(prompt_version_id="hr:v1", knowledge_base_ids=[])
    store.factory.return_value.__enter__.return_value = db
    data = {
        "thread_id": "case-thread",
        "run_id": "case-run",
        "status": "completed",
        "result": {
            "route": route,
            "response_kind": response_kind,
            "status": status,
            "output_text": "你好！我可以帮助查询员工制度。",
        },
        "usage": dict(
            model_calls=1,
            retrieval_calls=0,
            tool_calls=0,
            input_tokens=12,
            output_tokens=10,
            total_tokens=22,
            cost_microusd=None,
        ),
    }
    return score_case(case, data, {}, store, 1)


@pytest.mark.parametrize(
    "expected,route,kind,status,outcome,passed",
    [
        ("conversation", "direct", "conversation", "succeeded", "conversation", True),
        ("conversation", "direct", None, "succeeded", "answer", False),
        ("conversation", "retrieve", "conversation", "succeeded", "answer", False),
        ("conversation", "direct", "conversation", "abstained", "abstain", False),
        ("answer", "direct", None, "succeeded", "answer", False),
        ("answer", "direct", "conversation", "succeeded", "conversation", False),
    ],
)
def test_conversation_scoring_requires_server_marker_without_weakening_business_evidence(
    expected, route, kind, status, outcome, passed
):
    result = score_public_reply(expected, route, kind, status)
    assert result.actual_outcome == outcome
    assert result.e2e_success is passed
    if expected == "conversation":
        assert result.abstention_correct is None


def test_conversation_metrics_do_not_inflate_business_or_abstention_denominators():
    conversation = score_public_reply("conversation", response_kind="conversation").model_copy(
        update={"answer_quality_passed": True}
    )
    business = score_public_reply("answer").model_copy(update={"answer_quality_passed": False})
    metrics = summarize([conversation, business])
    assert metrics["e2e_success_rate"] == 0.5
    assert metrics["business_e2e_success_rate"] == 0
    assert metrics["conversation_e2e_success_rate"] == 1
    assert metrics["denominators"]["business_e2e_success_rate"] == 1
    assert metrics["denominators"]["conversation_e2e_success_rate"] == 1
    assert metrics["denominators"]["abstention_accuracy"] == 1
    assert metrics["rubric_answer_pass_rate"] == 0
    assert metrics["conversation_rubric_pass_rate"] == 1
    assert metrics["denominators"]["rubric_answer_pass_rate"] == 1
    assert metrics["denominators"]["conversation_rubric_pass_rate"] == 1
    assert metrics["model_calls"] == 2


@pytest.mark.parametrize("command", ["eval", "eval-real"])
@pytest.mark.parametrize("explicit", [False, True])
def test_cli_uses_v3_by_default_and_preserves_explicit_historical_dataset(
    monkeypatch, command, explicit
):
    from omniagent import cli, eval_platform, real_baseline

    prefix = "real-" if command == "eval-real" else ""
    dataset = (
        Path(f"evals/{prefix}v2/cases.json") if explicit else Path(f"evals/{prefix}v3/cases.json")
    )
    args = ["omniagent", command] + (["--dataset", str(dataset)] if explicit else [])
    runner = MagicMock(return_value=make_run())
    module, name = (
        (real_baseline, "real_baseline") if command == "eval-real" else (eval_platform, "evaluate")
    )
    monkeypatch.setattr(module, name, runner)
    monkeypatch.setattr(cli, "configured_database_url", lambda _: "unused")
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 0
    assert runner.call_args.kwargs["dataset_path"] == dataset


@pytest.mark.parametrize(
    "case_id,answer,passed",
    [
        ("hr-13", "你好！我可以帮助查询员工制度。", True),
        ("hr-13", "Please provide a specific question.", False),
        ("conversation-hr-capabilities", "我可以查询员工制度，回答附原文引用。", True),
        (
            "conversation-support-capabilities",
            "可以查询产品使用与售后政策，查询产品资料和查询保修状态。",
            True,
        ),
        (
            "conversation-sales-capabilities",
            "可以查询销售与折扣政策、查询客户资料、拟定客户回访和发起折扣申请；写入须人工审批。",
            True,
        ),
        ("conversation-sales-viewer", "我可以查询销售与折扣政策，回答附原文引用。", True),
        (
            "conversation-sales-viewer",
            "我可以查询销售与折扣政策，回答附原文引用，也能查询客户资料。",
            False,
        ),
        (
            "conversation-sales-viewer",
            "我可以查询销售与折扣政策，回答附原文引用，也能拟定客户回访。",
            False,
        ),
        (
            "conversation-sales-viewer",
            "我可以查询销售与折扣政策，回答附原文引用，也能发起折扣申请。",
            False,
        ),
        ("conversation-sales-viewer", "销售与折扣政策有原文引用：折扣范围是 1% 到 20%。", False),
    ],
)
def test_public_help_rubrics_reject_language_policy_dump_and_role_overclaims(
    case_id, answer, passed
):
    dataset = EvalDataset.model_validate_json(
        Path("evals/v3/cases.json").read_text(encoding="utf-8")
    )
    rubric = next(case.answer_quality for case in dataset.cases if case.case_id == case_id)
    assert rubric is not None
    assert all(score_answer_quality(answer, rubric).values()) is passed


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


@pytest.mark.parametrize("mode,dataset", [("fake", "v1"), ("real", "real-v1")])
def test_new_optional_rubrics_do_not_rewrite_frozen_dataset_identity(mode, dataset):
    frozen = EvalDataset.model_validate_json(
        Path(f"evals/{dataset}/cases.json").read_text(encoding="utf-8")
    )
    archived = EvalRun.model_validate_json(
        Path(f"tests/fixtures/eval-legacy-{mode}.json").read_text(encoding="utf-8")
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
