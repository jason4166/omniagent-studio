from pathlib import Path

from omniagent.grounding_evaluation import (
    GroundingEvalReport,
    build_grounding_eval_markdown,
    build_grounding_eval_report,
    compute_file_sha256,
    save_grounding_eval_report,
)

GROUNDING_V1_PATH = Path("evals/grounding-v1.jsonl")
GROUNDING_V1_SHA256 = "427c985a528239a986de9e1a51e4a28128f0dcc47c84ed38c6710b429168c9d9"


def test_build_grounding_report_preserves_dataset_identity_and_denominators() -> None:
    report = build_grounding_eval_report(GROUNDING_V1_PATH)

    assert compute_file_sha256(GROUNDING_V1_PATH) == GROUNDING_V1_SHA256
    assert report.dataset_sha256 == GROUNDING_V1_SHA256
    assert report.summary.case_count == 14
    assert report.summary.correct_decision_count == 12
    assert report.summary.attempted_citation_count == 16
    assert report.summary.valid_citation_count == 12
    assert report.summary.evaluated_claim_count == 12
    assert report.summary.supported_claim_count == 4
    assert report.summary.unsupported_claim_count == 8


def test_grounding_markdown_reports_metrics_and_negative_case_interpretation() -> None:
    markdown = build_grounding_eval_markdown(build_grounding_eval_report(GROUNDING_V1_PATH))

    assert "| Citation validity | 12 | 16 | 0.7500 |" in markdown
    assert "| Claim support | 4 | 12 | 0.3333 |" in markdown
    assert "| grounding-007 | unauthorized_id | abstain | abstain |" in markdown
    assert "include deliberately invalid drafts" in markdown


def test_save_grounding_report_writes_valid_json_and_markdown(tmp_path: Path) -> None:
    report = build_grounding_eval_report(GROUNDING_V1_PATH)

    json_path, markdown_path = save_grounding_eval_report(
        report,
        tmp_path / "grounding",
    )

    loaded = GroundingEvalReport.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert loaded == report
    assert markdown_path.read_text(encoding="utf-8") == build_grounding_eval_markdown(report)
