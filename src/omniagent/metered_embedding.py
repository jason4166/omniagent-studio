"""Reserve a conservative retry-inclusive embedding allowance before paid requests."""

from collections.abc import Sequence

from omniagent.access import AccessService
from omniagent.embeddings import EmbeddingProvider, embedding_identity
from omniagent.identity import DevUserContext


class MeteredEmbedding:
    def __init__(self, provider: EmbeddingProvider, access: AccessService, actor: DevUserContext):
        self.provider = provider
        self.access = access
        self.actor = actor
        self.model_name = provider.model_name
        self.dimension = provider.dimension
        self.index_version = embedding_identity(provider)

    @property
    def last_input_tokens(self) -> int | None:
        usage = getattr(self.provider, "last_input_tokens", None)
        return usage if isinstance(usage, int) else None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if texts and self.access.settings.mode != "dev":
            self.access.validate_actor(self.actor)
            units = max(1, sum(len(value.encode("utf-8")) for value in texts) * 2)
            self.access.reserve(
                [
                    ("embedding:" + self.actor.user_id, units, 2000000),
                    ("embedding:global", units, 10000000),
                ]
            )
        return self.provider.embed(texts)
