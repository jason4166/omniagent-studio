import pytest
from pydantic import ValidationError

from omniagent.grounding import (
    AnswerDraft,
    Claim,
    ConflictCandidate,
    ConflictStatement,
    build_context_pack,
    decide_grounding_outcome,
    evaluate_answer_draft,
    validate_conflict_evidence,
)
from omniagent.retrieval import RetrievalHit, SourceLocator
from omniagent.runtime import RuntimeResult, runtime_result_from_grounding_decision


def retrieval_hit(
    *,
    rank: int,
    chunk_id: str,
    content: str,
    source_name: str,
) -> RetrievalHit:
    return RetrievalHit(
        retrieval_mode="vector",
        chunk_id=chunk_id,
        source_id=f"source-{chunk_id}",
        knowledge_base_id="kb-support",
        chunk_index=rank - 1,
        content=content,
        rank=rank,
        vector_rank=rank,
        vector_distance=0.0,
        final_score=1.0,
        source_locator=SourceLocator(
            source_name=source_name,
            page_number=rank,
            section="Refund window",
            char_start=0,
            char_end=len(content),
        ),
    )


def test_grounded_runtime_result_exposes_claim_labels_and_source_locator() -> None:
    content = "Standard purchases may be refunded within thirty days."
    context_pack = build_context_pack(
        [
            retrieval_hit(
                rank=1,
                chunk_id="chunk-window",
                content=content,
                source_name="refund-policy.pdf",
            )
        ],
        authorized_knowledge_base_ids={"kb-support"},
        max_content_characters=200,
    )
    decision = evaluate_answer_draft(
        AnswerDraft(claims=(Claim(claim_id="CL1", text=content, citation_labels=("C1",)),)),
        context_pack,
        authorized_knowledge_base_ids={"kb-support"},
    )

    result = runtime_result_from_grounding_decision(
        profile_id="support",
        thread_id="thread-001",
        decision=decision,
    )
    body = result.model_dump(mode="json")

    assert result.status == "succeeded"
    assert result.route == "retrieve"
    assert body["claims"] == [{"claim_id": "CL1", "text": content, "citation_labels": ["C1"]}]
    assert body["citations"][0]["citation_label"] == "C1"
    assert body["citations"][0]["source_id"] == "source-chunk-window"
    assert body["citations"][0]["source_locator"] == {
        "source_name": "refund-policy.pdf",
        "page_number": 1,
        "section": "Refund window",
        "char_start": 0,
        "char_end": len(content),
    }
    assert len(body["citations"][0]["content_sha256"]) == 64


def test_unsupported_answer_is_rejected_before_runtime_output() -> None:
    content = "Standard purchases may be refunded within thirty days."
    context_pack = build_context_pack(
        [
            retrieval_hit(
                rank=1,
                chunk_id="chunk-window",
                content=content,
                source_name="refund-policy.pdf",
            )
        ],
        authorized_knowledge_base_ids={"kb-support"},
        max_content_characters=200,
    )
    decision = evaluate_answer_draft(
        AnswerDraft(
            claims=(
                Claim(
                    claim_id="CL1",
                    text="Refunds are available forever.",
                    citation_labels=("C1",),
                ),
            )
        ),
        context_pack,
        authorized_knowledge_base_ids={"kb-support"},
    )

    result = runtime_result_from_grounding_decision(
        profile_id="support",
        thread_id="thread-002",
        decision=decision,
    )

    assert result.status == "rejected"
    assert result.output_text is None
    assert result.claims == ()
    assert result.citations == ()
    assert result.error is not None
    assert result.error.code == "unsupported_claim"


def test_conflict_runtime_result_returns_both_locatable_citations() -> None:
    first = "The current refund window is thirty days."
    second = "The current refund window is fourteen days."
    context_pack = build_context_pack(
        [
            retrieval_hit(
                rank=1,
                chunk_id="chunk-old",
                content=first,
                source_name="old-policy.pdf",
            ),
            retrieval_hit(
                rank=2,
                chunk_id="chunk-new",
                content=second,
                source_name="new-policy.pdf",
            ),
        ],
        authorized_knowledge_base_ids={"kb-support"},
        max_content_characters=200,
    )
    conflict = validate_conflict_evidence(
        ConflictCandidate(
            topic="Current refund window",
            statements=(
                ConflictStatement(citation_label="C1", quote=first),
                ConflictStatement(citation_label="C2", quote=second),
            ),
        ),
        context_pack,
        authorized_knowledge_base_ids={"kb-support"},
    )

    result = runtime_result_from_grounding_decision(
        profile_id="support",
        thread_id="thread-003",
        decision=decide_grounding_outcome(conflict=conflict),
    )

    assert result.status == "succeeded"
    assert result.claims == ()
    assert [citation.citation_label for citation in result.citations] == ["C1", "C2"]
    assert [citation.source_locator.source_name for citation in result.citations] == [
        "old-policy.pdf",
        "new-policy.pdf",
    ]


def test_runtime_result_rejects_grounding_data_on_a_direct_route() -> None:
    content = "Standard purchases may be refunded within thirty days."
    context_pack = build_context_pack(
        [
            retrieval_hit(
                rank=1,
                chunk_id="chunk-window",
                content=content,
                source_name="refund-policy.pdf",
            )
        ],
        authorized_knowledge_base_ids={"kb-support"},
        max_content_characters=200,
    )
    decision = evaluate_answer_draft(
        AnswerDraft(claims=(Claim(claim_id="CL1", text=content, citation_labels=("C1",)),)),
        context_pack,
        authorized_knowledge_base_ids={"kb-support"},
    )
    assert decision.grounded_answer is not None

    with pytest.raises(
        ValidationError,
        match="grounding data requires a succeeded retrieve result",
    ):
        RuntimeResult(
            profile_id="support",
            thread_id="thread-004",
            status="succeeded",
            route="direct",
            output_text=content,
            claims=decision.grounded_answer.claims,
            citations=decision.grounded_answer.citations,
        )
