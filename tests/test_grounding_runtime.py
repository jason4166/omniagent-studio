import json

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
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
from omniagent.grounding_runtime import (
    GroundingProposal,
    GroundingRuntime,
    parse_grounding_proposal,
)
from omniagent.llm import FakeLLM, LLMInvalidOutputError, LLMResponse
from omniagent.retrieval import RetrievalHit, SourceLocator
from omniagent.runtime import RuntimeResult, runtime_result_from_grounding_decision

PROPOSAL_EXAMPLES = {
    "answer_draft": {
        "claims": [
            {
                "claim_id": "CL1",
                "text": "Refunds are available for thirty days.",
                "citation_labels": ["C1"],
            }
        ]
    },
    "conflict_candidate": {
        "topic": "Refund window",
        "statements": [
            {"citation_label": "C1", "quote": "Refunds are available for thirty days."},
            {"citation_label": "C2", "quote": "Refunds are available for fourteen days."},
        ],
    },
    "clarification_question": "Which purchase are you asking about?",
    "abstention_reason": "The supplied evidence does not describe this policy.",
}


@pytest.mark.parametrize("selected", list(PROPOSAL_EXAMPLES))
def test_grounding_schema_and_parser_accept_one_proposal_with_omitted_or_null_others(selected):
    schema = GroundingProposal.model_json_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for explicit_nulls in (False, True):
        payload = dict.fromkeys(PROPOSAL_EXAMPLES) if explicit_nulls else {}
        payload[selected] = PROPOSAL_EXAMPLES[selected]
        validator.validate(payload)
        parsed = parse_grounding_proposal(LLMResponse(model="fake-v1", content=json.dumps(payload)))
        assert parsed.model_dump(mode="json", exclude_none=True) == {
            selected: PROPOSAL_EXAMPLES[selected]
        }


@pytest.mark.parametrize(
    "selected",
    [
        (),
        ("clarification_question", "abstention_reason"),
        ("answer_draft", "conflict_candidate"),
        tuple(PROPOSAL_EXAMPLES),
    ],
)
def test_grounding_schema_and_parser_reject_missing_or_conflicting_proposal_types(selected):
    validator = Draft202012Validator(GroundingProposal.model_json_schema())
    for explicit_nulls in (False, True):
        payload = dict.fromkeys(PROPOSAL_EXAMPLES) if explicit_nulls else {}
        payload.update({field: PROPOSAL_EXAMPLES[field] for field in selected})
        with pytest.raises(SchemaValidationError):
            validator.validate(payload)
        with pytest.raises(ValidationError, match="exactly one response type"):
            GroundingProposal.model_validate(payload)
        with pytest.raises(LLMInvalidOutputError):
            parse_grounding_proposal(LLMResponse(model="fake-v1", content=json.dumps(payload)))


def test_grounding_runtime_never_chooses_between_clarification_and_abstention():
    payload = {
        field: PROPOSAL_EXAMPLES[field] for field in ("clarification_question", "abstention_reason")
    }
    provider = FakeLLM(LLMResponse(model="fake-v1", content=json.dumps(payload)))

    class Retriever:
        def retrieve_hits(self, knowledge_base_ids, query):
            return [
                retrieval_hit(
                    rank=1,
                    chunk_id="chunk-window",
                    content="Refunds are available for thirty days.",
                    source_name="policy.md",
                )
            ]

    runtime = GroundingRuntime(
        retriever=Retriever(), provider=provider, model="fake-v1", max_content_characters=200
    )
    result = runtime.run(
        profile_id="support",
        thread_id="proposal-parity",
        query="What policy applies?",
        authorized_knowledge_base_ids=["kb-support"],
    )
    assert result.status == "failed"
    assert result.error.code == "invalid_model_output"
    assert result.output_text is None
    assert result.claims == result.citations == ()
    assert len(provider.requests) == 1
    sent = provider.requests[0]
    assert "abstention_reason" in sent.messages[0].content
    assert "exactly ONE" in sent.messages[0].content
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(sent.response_schema).validate(payload)


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
