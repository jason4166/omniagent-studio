from sqlalchemy.orm import Session, sessionmaker

from omniagent.embeddings import EmbeddingProvider
from omniagent.postgres_repositories import (
    SqlAlchemyKnowledgeRepository,
)
from omniagent.retrieval import RetrievalHit, TextQueryOperator
from omniagent.retrieval_metrics import rrf_fuse


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
        matches = self.retrieve_hits(knowledge_base_ids, query)

        return "\n\n".join(match.content for match in matches)

    def retrieve_hits(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> list[RetrievalHit]:
        with self._session_factory() as session:
            repository = SqlAlchemyKnowledgeRepository(
                session,
                self._embedding_provider,
            )
            return repository.search_vector_hits(
                knowledge_base_ids=knowledge_base_ids,
                query=query,
                top_k=self._top_k,
            )


class PgTextRetriever:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        top_k: int = 5,
        *,
        query_operator: TextQueryOperator = "and",
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive")

        self._session_factory = session_factory
        self._embedding_provider = embedding_provider
        self._top_k = top_k
        self._query_operator = query_operator

    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str:
        matches = self.retrieve_hits(knowledge_base_ids, query)
        return "\n\n".join(match.content for match in matches)

    def retrieve_hits(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> list[RetrievalHit]:
        with self._session_factory() as session:
            repository = SqlAlchemyKnowledgeRepository(
                session,
                self._embedding_provider,
            )
            return repository.search_text_hits(
                knowledge_base_ids=knowledge_base_ids,
                query=query,
                top_k=self._top_k,
                query_operator=self._query_operator,
            )


class HybridRetriever:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        *,
        top_k: int = 5,
        candidate_k: int = 20,
        rank_constant: int = 60,
        text_query_operator: TextQueryOperator = "and",
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        if candidate_k < top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        if rank_constant < 0:
            raise ValueError("rank_constant must not be negative")

        self._session_factory = session_factory
        self._embedding_provider = embedding_provider
        self._top_k = top_k
        self._candidate_k = candidate_k
        self._rank_constant = rank_constant
        self._text_query_operator = text_query_operator

    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str:
        matches = self.retrieve_hits(knowledge_base_ids, query)
        return "\n\n".join(match.content for match in matches)

    def retrieve_hits(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> list[RetrievalHit]:
        with self._session_factory() as session:
            repository = SqlAlchemyKnowledgeRepository(
                session,
                self._embedding_provider,
            )
            vector_hits = repository.search_vector_hits(
                knowledge_base_ids=knowledge_base_ids,
                query=query,
                top_k=self._candidate_k,
            )
            text_hits = repository.search_text_hits(
                knowledge_base_ids=knowledge_base_ids,
                query=query,
                top_k=self._candidate_k,
                query_operator=self._text_query_operator,
            )

        vector_by_id = {hit.chunk_id: hit for hit in vector_hits}
        text_by_id = {hit.chunk_id: hit for hit in text_hits}
        fused_ranks = rrf_fuse(
            [
                [hit.chunk_id for hit in vector_hits],
                [hit.chunk_id for hit in text_hits],
            ],
            rank_constant=self._rank_constant,
        )

        results: list[RetrievalHit] = []
        for fused in fused_ranks[: self._top_k]:
            vector_hit = vector_by_id.get(fused.chunk_id)
            text_hit = text_by_id.get(fused.chunk_id)
            source_hit = vector_hit or text_hit
            if source_hit is None:
                raise RuntimeError("fused chunk is missing its source hit")

            results.append(
                RetrievalHit(
                    retrieval_mode="hybrid",
                    chunk_id=source_hit.chunk_id,
                    source_id=source_hit.source_id,
                    knowledge_base_id=source_hit.knowledge_base_id,
                    chunk_index=source_hit.chunk_index,
                    content=source_hit.content,
                    rank=fused.rank,
                    vector_rank=(vector_hit.vector_rank if vector_hit is not None else None),
                    vector_distance=(
                        vector_hit.vector_distance if vector_hit is not None else None
                    ),
                    text_rank=(text_hit.text_rank if text_hit is not None else None),
                    text_score=(text_hit.text_score if text_hit is not None else None),
                    final_score=fused.score,
                    source_locator=source_hit.source_locator,
                )
            )

        return results
