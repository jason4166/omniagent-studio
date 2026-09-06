import pytest
from pydantic import ValidationError

from omniagent.retrieval import FakeRetriever, RetrievalHit, Retriever, SourceLocator


def test_fake_retriever_returns_configured_response_and_records_request() -> None:
    fake_retriever = FakeRetriever(
        response="Synthetic knowledge: remote support is available from 09:00 to 18:00."
    )
    retriever: Retriever = fake_retriever

    result = retriever.retrieve(
        knowledge_base_ids=["general-kb-v1"],
        query="What are the synthetic remote-support hours?",
    )

    assert result == "Synthetic knowledge: remote support is available from 09:00 to 18:00."
    assert fake_retriever.requests == [
        (
            ("general-kb-v1",),
            "What are the synthetic remote-support hours?",
        )
    ]


def test_retrieval_hit_preserves_both_rankings_scores_and_source_locator() -> None:
    hit = RetrievalHit(
        retrieval_mode="hybrid",
        chunk_id="chunk-refund-deadline",
        source_id="source-refund-policy",
        knowledge_base_id="kb-support",
        chunk_index=2,
        content="Standard purchases may be refunded within thirty days.",
        rank=1,
        vector_rank=2,
        vector_distance=0.18,
        text_rank=1,
        text_score=0.42,
        final_score=(1 / 62) + (1 / 61),
        source_locator=SourceLocator(
            source_name="refund-policy.md",
            page_number=None,
            section="Refund window",
            char_start=120,
            char_end=178,
        ),
    )

    assert hit.rank == 1
    assert hit.vector_rank == 2
    assert hit.text_rank == 1
    assert hit.source_locator.section == "Refund window"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"vector_rank": None},
            "vector_rank and vector_distance must appear together",
        ),
        (
            {"retrieval_mode": "text"},
            "text hits require only text rank and score",
        ),
        (
            {
                "retrieval_mode": "hybrid",
                "vector_rank": None,
                "vector_distance": None,
            },
            "hybrid hits require at least one source ranking",
        ),
    ],
)
def test_retrieval_hit_rejects_inconsistent_mode_scores(
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "retrieval_mode": "vector",
        "chunk_id": "chunk-refund-deadline",
        "source_id": "source-refund-policy",
        "knowledge_base_id": "kb-support",
        "chunk_index": 0,
        "content": "Standard purchases may be refunded within thirty days.",
        "rank": 1,
        "vector_rank": 1,
        "vector_distance": 0.18,
        "final_score": -0.18,
        "source_locator": SourceLocator(
            source_name="refund-policy.md",
            page_number=None,
            section="Refund window",
            char_start=0,
            char_end=58,
        ),
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        RetrievalHit.model_validate(values)
