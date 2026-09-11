import pytest

from omniagent.grounding import (
    AnswerDraft,
    Claim,
    ConflictCandidate,
    ConflictStatement,
    GroundingValidationError,
    build_context_pack,
    evaluate_answer_draft,
    validate_conflict_evidence,
)
from omniagent.retrieval import RetrievalHit, SourceLocator


def evidence(content: str, rank: int = 1) -> RetrievalHit:
    return RetrievalHit(
        retrieval_mode="vector",
        chunk_id=f"chunk-{rank}",
        source_id=f"source-{rank}",
        knowledge_base_id="policy",
        chunk_index=0,
        content=content,
        rank=rank,
        vector_rank=rank,
        vector_distance=0.1,
        final_score=0.9,
        source_locator=SourceLocator(
            source_name=f"policy-{rank}.txt", char_start=0, char_end=len(content)
        ),
    )


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("公司不允许远程办公。", "允许远程办公。"),
        ("仅当经理批准后，员工可以远程办公。", "员工可以远程办公。"),
        ("Employees may work remotely, except during probation.", "Employees may work remotely"),
        ("可申请退款。已拆封商品除外。", "可申请退款。"),
        ("适用条件：\n经理已批准。\n\n员工可以远程办公。", "员工可以远程办公。"),
    ],
)
def test_claim_cannot_drop_negation_condition_or_adjacent_exception(content, fragment):
    pack = build_context_pack(
        [evidence(content)], authorized_knowledge_base_ids=["policy"], max_content_characters=500
    )
    decision = evaluate_answer_draft(
        AnswerDraft(claims=(Claim(claim_id="CL1", text=fragment, citation_labels=("C1",)),)),
        pack,
        authorized_knowledge_base_ids=["policy"],
    )
    assert decision.outcome == "abstain"
    assert decision.failure_code == "unsupported_claim"
    assert decision.grounded_answer is None


def test_whole_evidence_unit_preserves_all_conditions_in_server_output():
    content = "  适用条件：经理已批准。\n员工可以远程办公。\n试用期除外。\n"
    pack = build_context_pack(
        [evidence(content)], authorized_knowledge_base_ids=["policy"], max_content_characters=500
    )
    decision = evaluate_answer_draft(
        AnswerDraft(claims=(Claim(claim_id="CL1", text=content, citation_labels=("C1",)),)),
        pack,
        authorized_knowledge_base_ids=["policy"],
    )
    assert decision.outcome == "answer"
    assert decision.grounded_answer is not None
    assert decision.grounded_answer.claims[0].text == content.strip()
    assert decision.grounded_answer.support_method == "complete_evidence_unit"
    assert decision.grounded_answer.citations[0].content_sha256 == pack.evidence[0].content_sha256


def test_context_budget_never_keeps_a_claim_while_truncating_its_exception():
    first = "适用退款规则。"
    content = "可申请退款。已拆封商品除外。"
    pack = build_context_pack(
        [evidence(first), evidence(content, rank=2)],
        authorized_knowledge_base_ids=["policy"],
        max_content_characters=len(first) + len("可申请退款。"),
    )
    assert pack.truncated is True
    assert [item.content for item in pack.evidence] == [first]
    assert pack.used_content_characters == len(first)


def test_conflict_quote_cannot_drop_the_exception_that_removes_a_conflict():
    pack = build_context_pack(
        [evidence("可申请退款。已拆封商品除外。"), evidence("已拆封商品不可退款。", rank=2)],
        authorized_knowledge_base_ids=["policy"],
        max_content_characters=500,
    )
    candidate = ConflictCandidate(
        topic="已拆封商品退款",
        statements=(
            ConflictStatement(citation_label="C1", quote="可申请退款。"),
            ConflictStatement(citation_label="C2", quote="已拆封商品不可退款。"),
        ),
    )
    with pytest.raises(GroundingValidationError) as failure:
        validate_conflict_evidence(candidate, pack, authorized_knowledge_base_ids=["policy"])
    assert failure.value.code == "unanchored_conflict"
