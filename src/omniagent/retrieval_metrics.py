from pydantic import BaseModel, ConfigDict, Field


class FusedRank(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)


def calculate_recall_at_k(
    relevant_ids: set[str],
    retrieved_ids: list[str],
    k: int,
) -> float:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")

    retrieved_at_k = set(retrieved_ids[:k])
    matched_ids = relevant_ids & retrieved_at_k
    return len(matched_ids) / len(relevant_ids)


def calculate_reciprocal_rank(
    relevant_ids: set[str],
    retrieved_ids: list[str],
) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")

    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant_ids:
            return 1 / rank

    return 0.0


def calculate_mrr(
    relevant_id_sets: list[set[str]],
    retrieved_id_lists: list[list[str]],
) -> float:
    if not relevant_id_sets:
        raise ValueError("at least one answerable query is required")
    if len(relevant_id_sets) != len(retrieved_id_lists):
        raise ValueError("relevant and retrieved query counts must match")

    reciprocal_ranks = [
        calculate_reciprocal_rank(relevant_ids, retrieved_ids)
        for relevant_ids, retrieved_ids in zip(
            relevant_id_sets,
            retrieved_id_lists,
            strict=True,
        )
    ]
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def rrf_fuse(
    rankings: list[list[str]],
    rank_constant: int = 60,
) -> list[FusedRank]:
    if rank_constant < 0:
        raise ValueError("rank_constant must not be negative")

    scores: dict[str, float] = {}

    for ranking in rankings:
        if len(ranking) != len(set(ranking)):
            raise ValueError("each ranking must contain unique chunk IDs")

        for rank, chunk_id in enumerate(ranking, start=1):
            if not chunk_id:
                raise ValueError("chunk IDs must not be empty")
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (rank_constant + rank)

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        FusedRank(chunk_id=chunk_id, rank=rank, score=score)
        for rank, (chunk_id, score) in enumerate(ordered, start=1)
    ]
