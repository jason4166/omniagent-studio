import pytest

from omniagent.retrieval_metrics import (
    calculate_mrr,
    calculate_recall_at_k,
    calculate_reciprocal_rank,
    rrf_fuse,
)


def test_recall_at_k_counts_unique_relevant_hits() -> None:
    relevant_ids = {"chunk-refund-deadline", "chunk-refund-proof"}
    retrieved_ids = [
        "chunk-refund-proof",
        "chunk-refund-proof",
        "chunk-shipping-speed",
        "chunk-refund-deadline",
    ]

    assert calculate_recall_at_k(relevant_ids, retrieved_ids, 1) == 0.5
    assert calculate_recall_at_k(relevant_ids, retrieved_ids, 3) == 0.5
    assert calculate_recall_at_k(relevant_ids, retrieved_ids, 5) == 1.0


@pytest.mark.parametrize(
    ("relevant_ids", "k", "message"),
    [
        ({"chunk-refund-deadline"}, 0, "k must be positive"),
        (set(), 1, "relevant_ids must not be empty"),
    ],
)
def test_recall_at_k_rejects_undefined_inputs(
    relevant_ids: set[str],
    k: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_recall_at_k(relevant_ids, [], k)


def test_reciprocal_rank_uses_first_relevant_result() -> None:
    relevant_ids = {"chunk-refund-deadline", "chunk-refund-proof"}

    assert (
        calculate_reciprocal_rank(
            relevant_ids,
            ["chunk-shipping-speed", "chunk-refund-proof", "chunk-refund-deadline"],
        )
        == 0.5
    )
    assert calculate_reciprocal_rank(relevant_ids, ["chunk-shipping-speed"]) == 0.0


def test_mrr_averages_answerable_queries() -> None:
    assert calculate_mrr(
        [
            {"chunk-refund-deadline"},
            {"chunk-refund-proof"},
            {"chunk-shipping-speed"},
        ],
        [
            ["chunk-refund-proof", "chunk-refund-deadline", "chunk-shipping-speed"],
            ["chunk-refund-proof", "chunk-shipping-speed", "chunk-refund-deadline"],
            ["chunk-refund-deadline", "chunk-refund-proof", "chunk-shipping-speed"],
        ],
    ) == pytest.approx(11 / 18)


def test_rrf_fuse_matches_hand_calculation() -> None:
    fused = rrf_fuse(
        [
            ["chunk-refund-proof", "chunk-refund-deadline", "chunk-shipping-speed"],
            ["chunk-refund-deadline", "chunk-shipping-speed", "chunk-refund-proof"],
        ]
    )

    assert [item.chunk_id for item in fused] == [
        "chunk-refund-deadline",
        "chunk-refund-proof",
        "chunk-shipping-speed",
    ]
    assert fused[0].score == pytest.approx((1 / 62) + (1 / 61))
    assert fused[1].score == pytest.approx((1 / 61) + (1 / 63))
    assert fused[2].score == pytest.approx((1 / 63) + (1 / 62))
    assert [item.rank for item in fused] == [1, 2, 3]


def test_rrf_fuse_uses_chunk_id_as_deterministic_tie_breaker() -> None:
    fused = rrf_fuse(
        [
            ["chunk-b", "chunk-a"],
            ["chunk-a", "chunk-b"],
        ]
    )

    assert [item.chunk_id for item in fused] == ["chunk-a", "chunk-b"]


def test_rrf_fuse_rejects_duplicate_ids_within_one_ranking() -> None:
    with pytest.raises(ValueError, match="each ranking must contain unique chunk IDs"):
        rrf_fuse([["chunk-a", "chunk-a"]])
