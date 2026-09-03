from sqlalchemy.orm import Session, sessionmaker

from omniagent.embeddings import EmbeddingProvider
from omniagent.postgres_repositories import (
    SqlAlchemyKnowledgeRepository,
)


class PgVectorRetriever:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        top_k: int = 5,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive")

        self._session_factory = session_factory
        self._embedding_provider = embedding_provider
        self._top_k = top_k

    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str:
        with self._session_factory() as session:
            repository = SqlAlchemyKnowledgeRepository(
                session,
                self._embedding_provider,
            )
            matches = repository.search_chunks(
                knowledge_base_ids=knowledge_base_ids,
                query=query,
                top_k=self._top_k,
            )

        return "\n\n".join(
            match.content
            for match in matches
        )