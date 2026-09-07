import math
from collections.abc import Sequence

import pytest

from omniagent.embeddings import (
    EMBEDDING_DIMENSION,
    EmbeddingProvider,
    EmbeddingValidationError,
    FakeEmbedding,
    embed_checked,
)


class StubEmbedding:
    model_name = "stub"

    def __init__(self, *, dimension: int, vectors: list[list[float]]) -> None:
        self.dimension = dimension
        self._vectors = vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._vectors


def test_fake_embedding_is_deterministic_normalized_and_fixed_width() -> None:
    provider: EmbeddingProvider = FakeEmbedding()

    vectors = embed_checked(provider, ["退款规则", "退款规则", "招聘政策"])

    assert vectors[0] == vectors[1]
    assert vectors[0] != vectors[2]
    assert all(len(vector) == EMBEDDING_DIMENSION for vector in vectors)
    assert math.sqrt(sum(value * value for value in vectors[0])) == pytest.approx(1.0)
    assert all(value == 0.0 for value in vectors[0][8:])


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        (
            StubEmbedding(
                dimension=EMBEDDING_DIMENSION - 1,
                vectors=[[0.0] * (EMBEDDING_DIMENSION - 1)],
            ),
            f"provider dimension must be {EMBEDDING_DIMENSION}",
        ),
        (
            StubEmbedding(dimension=EMBEDDING_DIMENSION, vectors=[]),
            "provider must return one vector for each text",
        ),
        (
            StubEmbedding(
                dimension=EMBEDDING_DIMENSION,
                vectors=[[0.0] * (EMBEDDING_DIMENSION - 1)],
            ),
            f"vector 0 must have {EMBEDDING_DIMENSION} dimensions",
        ),
        (
            StubEmbedding(
                dimension=EMBEDDING_DIMENSION,
                vectors=[[float("nan"), *([0.0] * (EMBEDDING_DIMENSION - 1))]],
            ),
            "vector 0 must contain only finite numbers",
        ),
    ],
)
def test_embed_checked_rejects_invalid_provider_output(
    provider: EmbeddingProvider,
    message: str,
) -> None:
    with pytest.raises(EmbeddingValidationError, match=message):
        embed_checked(provider, ["退款规则"])
