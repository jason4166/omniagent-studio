import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from omniagent.grounding_evaluation import (
    REQUIRED_GROUNDING_CATEGORIES,
    GroundingEvalCase,
    GroundingEvalDatasetError,
    load_grounding_eval_cases,
    run_grounding_eval,
    run_grounding_eval_case,
    summarize_grounding_eval,
    validate_grounding_eval_suite,
)

GROUNDING_V1_PATH = Path("evals/grounding-v1.jsonl")
GROUNDING_V1_SHA256 = "427c985a528239a986de9e1a51e4a28128f0dcc47c84ed38c6710b429168c9d9"


def valid_case(case_id: str = "grounding-001") -> dict[str, object]:
    return {
        "case_id": case_id,
        "query": "What is the refund window?",
        "category": "normal",
        "authorized_knowledge_base_ids": ["kb-support"],
        "max_content_characters": 100,
        "hits": [],
        "answer_draft": {
            "claims": [
                {
                    "claim_id": "CL1",
                    "text": "Thirty days.",
                    "citation_labels": ["C1"],
                }
            ]
        },
        "expected_outcome": "answer",
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_grounding_v1_has_frozen_labels_and_required_coverage() -> None:
    cases = load_grounding_eval_cases(GROUNDING_V1_PATH)
    validate_grounding_eval_suite(cases)

    assert len(cases) == 14
    assert REQUIRED_GROUNDING_CATEGORIES <= {case.category for case in cases}
    assert hashlib.sha256(GROUNDING_V1_PATH.read_bytes()).hexdigest() == GROUNDING_V1_SHA256


def test_grounding_eval_case_is_frozen() -> None:
    case = GroundingEvalCase.model_validate(valid_case())

    with pytest.raises(ValidationError, match="frozen_instance"):
        case.query = "Change the label after seeing results"


def test_load_grounding_eval_cases_preserves_order_and_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "grounding.jsonl"
    write_jsonl(dataset_path, [valid_case("grounding-001"), valid_case("grounding-002")])

    cases = load_grounding_eval_cases(dataset_path)

    assert [case.case_id for case in cases] == ["grounding-001", "grounding-002"]

    write_jsonl(dataset_path, [valid_case(), valid_case()])
    with pytest.raises(GroundingEvalDatasetError, match="Duplicate case_id"):
        load_grounding_eval_cases(dataset_path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "must not be empty"),
        ("\n", "Blank line at line 1"),
        ("not-json\n", "Invalid JSON at line 1"),
        ('{"case_id":"grounding-001"}\n', "Invalid GroundingEvalCase at line 1"),
    ],
)
def test_load_grounding_eval_cases_rejects_invalid_dataset(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    dataset_path = tmp_path / "grounding.jsonl"
    dataset_path.write_text(content, encoding="utf-8")

    with pytest.raises(GroundingEvalDatasetError, match=message):
        load_grounding_eval_cases(dataset_path)


def test_grounding_eval_suite_requires_twelve_cases_and_all_categories() -> None:
    too_small = [
        GroundingEvalCase.model_validate(valid_case(f"grounding-{index:03d}"))
        for index in range(1, 12)
    ]

    with pytest.raises(GroundingEvalDatasetError, match="at least 12 cases"):
        validate_grounding_eval_suite(too_small)

    twelve_normal_cases = too_small + [
        GroundingEvalCase.model_validate(valid_case("grounding-012"))
    ]
    with pytest.raises(GroundingEvalDatasetError, match="suite is missing"):
        validate_grounding_eval_suite(twelve_normal_cases)


def test_grounding_v1_deterministic_runner_matches_frozen_decisions() -> None:
    cases = load_grounding_eval_cases(GROUNDING_V1_PATH)

    results = [run_grounding_eval_case(case) for case in cases]

    assert all(result.outcome_correct for result in results)
    assert all(result.decision_correct for result in results)
    assert [result.actual_failure_code for result in results[4:9]] == [
        "missing_citation",
        "unknown_citation",
        "unauthorized_citation",
        "no_evidence",
        "unsupported_claim",
    ]
    assert results[11].actual_outcome == "conflict"
    assert results[12].actual_failure_code == "unanchored_conflict"
    assert results[13].actual_outcome == "clarify"


def test_grounding_v1_summary_uses_explicit_metric_denominators() -> None:
    summary = run_grounding_eval(load_grounding_eval_cases(GROUNDING_V1_PATH))

    assert summary.case_count == 14
    assert summary.correct_outcome_count == 14
    assert summary.correct_decision_count == 14
    assert summary.attempted_citation_count == 16
    assert summary.valid_citation_count == 12
    assert summary.evaluated_claim_count == 12
    assert summary.supported_claim_count == 6
    assert summary.unsupported_claim_count == 6
    assert summary.expected_abstention_count == 7
    assert summary.correct_abstention_count == 14
    assert summary.outcome_accuracy == 1.0
    assert summary.decision_accuracy == 1.0
    assert summary.citation_validity_rate == 0.75
    assert summary.claim_support_rate == 0.5
    assert summary.unsupported_claim_rate == 0.5
    assert summary.abstention_accuracy == 1.0


def test_summarize_grounding_eval_rejects_an_empty_result_set() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        summarize_grounding_eval([])
