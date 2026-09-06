import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from omniagent.retrieval import RetrievalHit, SourceLocator
from omniagent.retrieval_evaluation import (
    RetrievalEvalCase,
    RetrievalEvalContractError,
    RetrievalEvalDatasetError,
    RetrievalEvalSafetyError,
    load_retrieval_eval_cases,
    load_retrieval_eval_corpus,
    run_retrieval_eval,
    summarize_retrieval_eval,
)

PROJECT_ROOT = Path(__file__).parent.parent
RETRIEVAL_V1_PATH = PROJECT_ROOT / "evals" / "retrieval-v1.jsonl"
RETRIEVAL_V1_MANIFEST_PATH = PROJECT_ROOT / "evals" / "retrieval-v1" / "corpus.json"


class StubHitsRetriever:
    def __init__(self, hits_by_query: dict[str, list[RetrievalHit]]) -> None:
        self.hits_by_query = hits_by_query
        self.requests: list[tuple[tuple[str, ...], str]] = []

    def retrieve_hits(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> list[RetrievalHit]:
        self.requests.append((tuple(knowledge_base_ids), query))
        return list(self.hits_by_query[query])


def vector_hit(
    chunk_id: str,
    rank: int,
    *,
    knowledge_base_id: str = "kb-support",
) -> RetrievalHit:
    return RetrievalHit(
        retrieval_mode="vector",
        chunk_id=chunk_id,
        source_id="source-policy",
        knowledge_base_id=knowledge_base_id,
        chunk_index=rank - 1,
        content=f"content for {chunk_id}",
        rank=rank,
        vector_rank=rank,
        vector_distance=rank / 10,
        final_score=1 - (rank / 10),
        source_locator=SourceLocator(
            source_name="policy.md",
            section="Policy",
            char_start=0,
            char_end=10,
        ),
    )


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def valid_case(case_id: str = "retrieval-001") -> dict[str, object]:
    return {
        "case_id": case_id,
        "query": "退款申请需要什么证明？",
        "category": "exact_name",
        "authorized_knowledge_base_ids": ["kb-support"],
        "relevant_chunk_ids": ["chunk-refund-proof"],
    }


def test_load_retrieval_eval_cases_preserves_file_order(tmp_path: Path) -> None:
    dataset_path = tmp_path / "retrieval-v1.jsonl"
    no_answer_case: dict[str, object] = {
        "case_id": "retrieval-002",
        "query": "公司是否提供火星搬家服务？",
        "category": "no_answer",
        "authorized_knowledge_base_ids": ["kb-support"],
        "relevant_chunk_ids": [],
    }
    write_jsonl(dataset_path, [valid_case(), no_answer_case])

    cases = load_retrieval_eval_cases(dataset_path)

    assert [case.case_id for case in cases] == ["retrieval-001", "retrieval-002"]
    assert cases[0].authorized_knowledge_base_ids == ("kb-support",)
    assert cases[0].relevant_chunk_ids == ("chunk-refund-proof",)
    assert cases[1].relevant_chunk_ids == ()


def test_retrieval_eval_case_is_frozen() -> None:
    case = RetrievalEvalCase.model_validate(valid_case())

    with pytest.raises(ValidationError, match="frozen_instance"):
        case.query = "看到结果后修改的问题"


def test_retrieval_v1_labels_reference_stable_authorized_chunks() -> None:
    corpus = load_retrieval_eval_corpus(RETRIEVAL_V1_MANIFEST_PATH)
    cases = load_retrieval_eval_cases(RETRIEVAL_V1_PATH)
    chunk_owners = {
        chunk.chunk_id: chunk.metadata.knowledge_base_id
        for source in corpus.sources
        for chunk in source.chunks
    }

    assert corpus.manifest.dataset_version == "retrieval-v1"
    assert len(cases) == 15
    assert {case.category for case in cases} == {
        "exact_name",
        "abbreviation",
        "paraphrase",
        "long_chinese",
        "no_answer",
        "cross_kb",
    }
    assert len(chunk_owners) == 11

    for case in cases:
        for chunk_id in case.relevant_chunk_ids:
            assert chunk_id in chunk_owners
            assert chunk_owners[chunk_id] in case.authorized_knowledge_base_ids


def test_retrieval_v1_has_two_no_answer_and_two_cross_kb_cases() -> None:
    cases = load_retrieval_eval_cases(RETRIEVAL_V1_PATH)

    assert sum(case.category == "no_answer" for case in cases) == 2
    assert sum(case.category == "cross_kb" for case in cases) == 2


def test_run_retrieval_eval_records_per_case_metrics_and_authorization() -> None:
    case = RetrievalEvalCase(
        case_id="retrieval-metrics",
        query="退款期限和证明",
        category="long_chinese",
        authorized_knowledge_base_ids=("kb-support",),
        relevant_chunk_ids=("chunk-deadline", "chunk-proof"),
    )
    retriever = StubHitsRetriever(
        {
            case.query: [
                vector_hit("chunk-shipping", 1),
                vector_hit("chunk-proof", 2),
                vector_hit("chunk-deadline", 3),
            ]
        }
    )

    result = run_retrieval_eval([case], retriever, retrieval_mode="vector")[0]

    assert retriever.requests == [(("kb-support",), "退款期限和证明")]
    assert result.retrieved_chunk_ids == (
        "chunk-shipping",
        "chunk-proof",
        "chunk-deadline",
    )
    assert result.recall_at_1 == 0.0
    assert result.recall_at_3 == 1.0
    assert result.recall_at_5 == 1.0
    assert result.reciprocal_rank == 0.5


def test_run_retrieval_eval_keeps_no_answer_metrics_separate() -> None:
    case = RetrievalEvalCase(
        case_id="retrieval-no-answer",
        query="火星搬家服务",
        category="no_answer",
        authorized_knowledge_base_ids=("kb-support",),
        relevant_chunk_ids=(),
    )
    retriever = StubHitsRetriever({case.query: [vector_hit("chunk-unrelated", 1)]})

    result = run_retrieval_eval([case], retriever, retrieval_mode="vector")[0]

    assert result.retrieved_chunk_ids == ("chunk-unrelated",)
    assert result.recall_at_1 is None
    assert result.recall_at_3 is None
    assert result.recall_at_5 is None
    assert result.reciprocal_rank is None


def test_run_retrieval_eval_stops_on_unauthorized_hit() -> None:
    case = RetrievalEvalCase.model_validate(valid_case())
    retriever = StubHitsRetriever(
        {
            case.query: [
                vector_hit(
                    "chunk-private",
                    1,
                    knowledge_base_id="kb-hr",
                )
            ]
        }
    )

    with pytest.raises(RetrievalEvalSafetyError, match="unauthorized knowledge bases"):
        run_retrieval_eval([case], retriever, retrieval_mode="vector")


@pytest.mark.parametrize(
    ("hits", "message"),
    [
        (
            [vector_hit("chunk-a", 1), vector_hit("chunk-a", 2)],
            "duplicate chunk IDs",
        ),
        (
            [vector_hit("chunk-a", 2)],
            "non-contiguous ranks",
        ),
    ],
)
def test_run_retrieval_eval_rejects_invalid_retriever_contract(
    hits: list[RetrievalHit],
    message: str,
) -> None:
    case = RetrievalEvalCase.model_validate(valid_case())
    retriever = StubHitsRetriever({case.query: hits})

    with pytest.raises(RetrievalEvalContractError, match=message):
        run_retrieval_eval([case], retriever, retrieval_mode="vector")


def test_summarize_retrieval_eval_aggregates_answerable_and_no_answer_separately() -> None:
    cases = [
        RetrievalEvalCase(
            case_id="answer-rank-1",
            query="answer-rank-1",
            category="exact_name",
            authorized_knowledge_base_ids=("kb-support",),
            relevant_chunk_ids=("chunk-a",),
        ),
        RetrievalEvalCase(
            case_id="answer-rank-2",
            query="answer-rank-2",
            category="paraphrase",
            authorized_knowledge_base_ids=("kb-support",),
            relevant_chunk_ids=("chunk-b",),
        ),
        RetrievalEvalCase(
            case_id="answer-missed",
            query="answer-missed",
            category="long_chinese",
            authorized_knowledge_base_ids=("kb-support",),
            relevant_chunk_ids=("chunk-c",),
        ),
        RetrievalEvalCase(
            case_id="no-answer-empty",
            query="no-answer-empty",
            category="no_answer",
            authorized_knowledge_base_ids=("kb-support",),
            relevant_chunk_ids=(),
        ),
        RetrievalEvalCase(
            case_id="no-answer-non-empty",
            query="no-answer-non-empty",
            category="no_answer",
            authorized_knowledge_base_ids=("kb-support",),
            relevant_chunk_ids=(),
        ),
    ]
    retriever = StubHitsRetriever(
        {
            "answer-rank-1": [vector_hit("chunk-a", 1)],
            "answer-rank-2": [
                vector_hit("chunk-x", 1),
                vector_hit("chunk-b", 2),
            ],
            "answer-missed": [vector_hit("chunk-x", 1)],
            "no-answer-empty": [],
            "no-answer-non-empty": [vector_hit("chunk-x", 1)],
        }
    )
    results = run_retrieval_eval(cases, retriever, retrieval_mode="vector")

    summary = summarize_retrieval_eval(results)

    assert summary.case_count == 5
    assert summary.answerable_case_count == 3
    assert summary.no_answer_case_count == 2
    assert summary.recall_at_1 == pytest.approx(1 / 3)
    assert summary.recall_at_3 == pytest.approx(2 / 3)
    assert summary.recall_at_5 == pytest.approx(2 / 3)
    assert summary.mrr == pytest.approx(0.5)
    assert summary.no_answer_empty_rate == 0.5


def test_summarize_retrieval_eval_uses_none_when_no_no_answer_cases_exist() -> None:
    case = RetrievalEvalCase.model_validate(valid_case())
    retriever = StubHitsRetriever({case.query: [vector_hit("chunk-refund-proof", 1)]})
    results = run_retrieval_eval([case], retriever, retrieval_mode="vector")

    summary = summarize_retrieval_eval(results)

    assert summary.no_answer_case_count == 0
    assert summary.no_answer_empty_rate is None


def test_summarize_retrieval_eval_rejects_duplicate_case_ids() -> None:
    case = RetrievalEvalCase.model_validate(valid_case())
    retriever = StubHitsRetriever({case.query: [vector_hit("chunk-refund-proof", 1)]})
    result = run_retrieval_eval([case], retriever, retrieval_mode="vector")[0]

    with pytest.raises(RetrievalEvalContractError, match="unique case IDs"):
        summarize_retrieval_eval([result, result])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("authorized_knowledge_base_ids", [], "at least 1 item"),
        (
            "authorized_knowledge_base_ids",
            ["kb-support", "kb-support"],
            "authorized knowledge base IDs must be unique",
        ),
        ("authorized_knowledge_base_ids", [" "], "must not be blank"),
        (
            "relevant_chunk_ids",
            ["chunk-refund-proof", "chunk-refund-proof"],
            "relevant chunk IDs must be unique",
        ),
        ("relevant_chunk_ids", [" "], "must not be blank"),
    ],
)
def test_retrieval_eval_case_rejects_invalid_id_collections(
    field: str,
    value: list[str],
    message: str,
) -> None:
    raw_case = valid_case()
    raw_case[field] = value

    with pytest.raises(ValidationError, match=message):
        RetrievalEvalCase.model_validate(raw_case)


def test_answerable_case_requires_relevant_chunk_ids() -> None:
    raw_case = valid_case()
    raw_case["relevant_chunk_ids"] = []

    with pytest.raises(ValidationError, match="answerable cases must contain"):
        RetrievalEvalCase.model_validate(raw_case)


def test_no_answer_case_rejects_relevant_chunk_ids() -> None:
    raw_case = valid_case()
    raw_case["category"] = "no_answer"

    with pytest.raises(ValidationError, match="no-answer cases must not contain"):
        RetrievalEvalCase.model_validate(raw_case)


def test_loader_rejects_duplicate_case_id(tmp_path: Path) -> None:
    dataset_path = tmp_path / "retrieval-v1.jsonl"
    write_jsonl(dataset_path, [valid_case(), valid_case()])

    with pytest.raises(RetrievalEvalDatasetError, match="Duplicate case_id at line 2"):
        load_retrieval_eval_cases(dataset_path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "must not be empty"),
        ("\n", "Blank line at line 1"),
        ("not-json\n", "Invalid JSON at line 1"),
        ('{"case_id":"missing-fields"}\n', "Invalid RetrievalEvalCase at line 1"),
    ],
)
def test_loader_rejects_invalid_dataset(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    dataset_path = tmp_path / "retrieval-v1.jsonl"
    dataset_path.write_text(content, encoding="utf-8")

    with pytest.raises(RetrievalEvalDatasetError, match=message):
        load_retrieval_eval_cases(dataset_path)
