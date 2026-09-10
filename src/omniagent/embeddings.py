import hashlib
import math
from collections.abc import Sequence
from typing import Protocol

from omniagent.telemetry import span

EMBEDDING_DIMENSION = 1024
_FAKE_SIGNAL_DIMENSION = 8


class EmbeddingProvider(Protocol):
    model_name: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingValidationError(ValueError):
    pass


class EmbeddingProviderError(RuntimeError):
    pass


def embedding_identity(provider: EmbeddingProvider) -> str:
    return str(getattr(provider, "index_version", None) or provider.model_name)


class FakeEmbedding:
    model_name = "fake-sha256-v1"
    dimension = EMBEDDING_DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    @staticmethod
    def _embed_one(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [(byte - 127.5) / 127.5 for byte in digest[:_FAKE_SIGNAL_DIMENSION]]
        norm = math.sqrt(sum(value * value for value in values))
        normalized = [value / norm for value in values]
        return [*normalized, *([0.0] * (EMBEDDING_DIMENSION - _FAKE_SIGNAL_DIMENSION))]


def embed_checked(
    provider: EmbeddingProvider,
    texts: Sequence[str],
) -> list[list[float]]:
    if provider.dimension != EMBEDDING_DIMENSION:
        raise EmbeddingValidationError(f"provider dimension must be {EMBEDDING_DIMENSION}")

    with span(
        "embedding", model_id=provider.model_name, index_version=embedding_identity(provider)
    ) as current:
        vectors = provider.embed(texts)
        usage = getattr(provider, "last_input_tokens", None)
        if isinstance(usage, int):
            current.set_attribute("input_tokens", usage)

    if len(vectors) != len(texts):
        raise EmbeddingValidationError("provider must return one vector for each text")

    for index, vector in enumerate(vectors):
        if len(vector) != EMBEDDING_DIMENSION:
            raise EmbeddingValidationError(
                f"vector {index} must have {EMBEDDING_DIMENSION} dimensions"
            )

        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingValidationError(f"vector {index} must contain only finite numbers")

    return vectors
