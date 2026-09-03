from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from omniagent.chunking import ChunkMetadata, DocumentChunk
from omniagent.db_models import (
    AgentProfileKnowledgeBaseRow,
    AgentProfileRow,
    AgentProfileToolRow,
    ChunkRow,
    KnowledgeBaseRow,
    PromptVersionRow,
    SourceRow,
    ToolDefinitionRow,
)
from omniagent.embeddings import EmbeddingProvider, embed_checked
from omniagent.ingestion import ParsedDocument, ParsedUnit
from omniagent.profiles import AgentProfile, KnowledgeBase, PromptVersion
from omniagent.prompts import PromptVersionAlreadyExistsError
from omniagent.retrieval import RetrievedChunk
from omniagent.tooling import ToolDefinition, ToolRisk


class SqlAlchemyPromptVersionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(
        self,
        prompt_version_id: str,
    ) -> PromptVersion | None:
        row = self._session.get(
            PromptVersionRow,
            prompt_version_id,
        )
        if row is None:
            return None

        return PromptVersion(
            prompt_version_id=row.prompt_version_id,
            content=row.content,
            content_hash=row.content_hash,
            variables=tuple(row.variables),
            created_at=row.created_at,
        )

    def save(
        self,
        prompt: PromptVersion,
    ) -> None:
        existing_row = self._session.get(
            PromptVersionRow,
            prompt.prompt_version_id,
        )
        if existing_row is not None:
            raise PromptVersionAlreadyExistsError(
                f"Prompt version '{prompt.prompt_version_id}' already exists"
            )

        row = PromptVersionRow(
            prompt_version_id=prompt.prompt_version_id,
            content=prompt.content,
            content_hash=prompt.content_hash,
            variables=list(prompt.variables),
            created_at=prompt.created_at,
        )
        self._session.add(row)


class SqlAlchemyToolDefinitionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: ToolDefinitionRow) -> ToolDefinition:
        return ToolDefinition(
            name=row.tool_id,
            risk=ToolRisk(row.risk),
            parameters_schema=dict(row.parameters_schema),
            allowed_roles=tuple(row.allowed_roles),
            tags=list(row.tags),
            requires_approval=row.requires_approval,
        )

    def get(self, tool_id: str) -> ToolDefinition | None:
        row = self._session.get(ToolDefinitionRow, tool_id)
        if row is None:
            return None
        return self._to_domain(row)

    def save(self, definition: ToolDefinition) -> None:
        row = self._session.get(ToolDefinitionRow, definition.name)
        if row is None:
            row = ToolDefinitionRow(tool_id=definition.name)
            self._session.add(row)

        row.risk = definition.risk.value
        row.parameters_schema = dict(definition.parameters_schema)
        row.allowed_roles = list(definition.allowed_roles)
        row.tags = list(definition.tags)
        row.requires_approval = definition.requires_approval

    def list_all(self) -> list[ToolDefinition]:
        statement = select(ToolDefinitionRow).order_by(ToolDefinitionRow.tool_id)
        return [self._to_domain(row) for row in self._session.scalars(statement)]


class SqlAlchemyAgentProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _to_domain(self, row: AgentProfileRow) -> AgentProfile:
        tool_statement = (
            select(AgentProfileToolRow.tool_id)
            .where(AgentProfileToolRow.profile_id == row.profile_id)
            .order_by(AgentProfileToolRow.tool_id)
        )
        knowledge_base_statement = (
            select(AgentProfileKnowledgeBaseRow.knowledge_base_id)
            .where(AgentProfileKnowledgeBaseRow.profile_id == row.profile_id)
            .order_by(AgentProfileKnowledgeBaseRow.knowledge_base_id)
        )

        return AgentProfile(
            profile_id=row.profile_id,
            version=row.version,
            enabled=row.enabled,
            tool_ids=list(self._session.scalars(tool_statement)),
            knowledge_base_ids=list(self._session.scalars(knowledge_base_statement)),
            prompt_version_id=row.prompt_version_id,
            budget_policy_id=row.budget_policy_id,
            approval_policy_id=row.approval_policy_id,
        )

    def get(self, profile_id: str) -> AgentProfile | None:
        row = self._session.get(AgentProfileRow, profile_id)
        if row is None:
            return None
        return self._to_domain(row)

    def save(self, profile: AgentProfile) -> None:
        row = self._session.get(AgentProfileRow, profile.profile_id)
        if row is None:
            row = AgentProfileRow(profile_id=profile.profile_id)
            self._session.add(row)

        row.version = profile.version
        row.enabled = profile.enabled
        row.prompt_version_id = profile.prompt_version_id
        row.budget_policy_id = profile.budget_policy_id
        row.approval_policy_id = profile.approval_policy_id

        self._session.execute(
            delete(AgentProfileToolRow).where(AgentProfileToolRow.profile_id == profile.profile_id)
        )
        self._session.execute(
            delete(AgentProfileKnowledgeBaseRow).where(
                AgentProfileKnowledgeBaseRow.profile_id == profile.profile_id
            )
        )

        self._session.add_all(
            [
                AgentProfileToolRow(
                    profile_id=profile.profile_id,
                    tool_id=tool_id,
                )
                for tool_id in profile.tool_ids
            ]
        )
        self._session.add_all(
            [
                AgentProfileKnowledgeBaseRow(
                    profile_id=profile.profile_id,
                    knowledge_base_id=knowledge_base_id,
                )
                for knowledge_base_id in profile.knowledge_base_ids
            ]
        )

    def list_all(self) -> list[AgentProfile]:
        statement = select(AgentProfileRow).order_by(AgentProfileRow.profile_id)
        return [self._to_domain(row) for row in self._session.scalars(statement)]


class SqlAlchemyKnowledgeRepository:
    def __init__(
        self,
        session: Session,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider

    def get_knowledge_base(
        self,
        knowledge_base_id: str,
    ) -> KnowledgeBase | None:
        row = self._session.get(
            KnowledgeBaseRow,
            knowledge_base_id,
        )
        if row is None:
            return None

        return KnowledgeBase(
            knowledge_base_id=row.knowledge_base_id,
            name=row.name,
        )

    def save_knowledge_base(
        self,
        knowledge_base: KnowledgeBase,
    ) -> None:
        row = KnowledgeBaseRow(
            knowledge_base_id=knowledge_base.knowledge_base_id,
            name=knowledge_base.name,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)

    def get_source(
        self,
        source_id: str,
    ) -> ParsedDocument | None:
        row = self._session.get(SourceRow, source_id)
        if row is None:
            return None

        units = tuple(ParsedUnit.model_validate(unit) for unit in row.units)

        return ParsedDocument(
            source_id=row.source_id,
            knowledge_base_id=row.knowledge_base_id,
            source_name=row.source_name,
            title=row.title,
            mime_type=row.mime_type,
            checksum=row.checksum,
            parser_version=row.parser_version,
            content=row.content,
            units=units,
        )

    def save_source(
        self,
        document: ParsedDocument,
        raw_bytes: bytes,
    ) -> None:
        units = [unit.model_dump(mode="json") for unit in document.units]

        row = SourceRow(
            source_id=document.source_id,
            knowledge_base_id=document.knowledge_base_id,
            source_name=document.source_name,
            title=document.title,
            mime_type=document.mime_type,
            checksum=document.checksum,
            parser_version=document.parser_version,
            content=document.content,
            units=units,
            raw_bytes=raw_bytes,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)

    def get_source_bytes(
        self,
        source_id: str,
    ) -> bytes | None:
        statement = select(SourceRow.raw_bytes).where(SourceRow.source_id == source_id)
        return self._session.scalar(statement)

    def save_chunks(
        self,
        source_id: str,
        chunks: list[DocumentChunk],
    ) -> None:
        for chunk in chunks:
            if chunk.metadata.source_id != source_id:
                raise ValueError("chunk source_id must match the requested source_id")

        texts = [chunk.content for chunk in chunks]
        vectors = embed_checked(
            self._embedding_provider,
            texts,
        )

        self._session.execute(delete(ChunkRow).where(ChunkRow.source_id == source_id))

        created_at = datetime.now(UTC)
        rows: list[ChunkRow] = []

        for chunk, vector in zip(chunks, vectors, strict=True):
            rows.append(
                ChunkRow(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.metadata.source_id,
                    knowledge_base_id=chunk.metadata.knowledge_base_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    chunk_metadata=chunk.metadata.model_dump(mode="json"),
                    embedding_model=self._embedding_provider.model_name,
                    embedding=vector,
                    created_at=created_at,
                )
            )

        self._session.add_all(rows)

    def list_chunks(
        self,
        source_id: str,
    ) -> list[DocumentChunk]:
        statement = (
            select(ChunkRow).where(ChunkRow.source_id == source_id).order_by(ChunkRow.chunk_index)
        )
        rows = self._session.scalars(statement).all()

        chunks: list[DocumentChunk] = []

        for row in rows:
            metadata = ChunkMetadata.model_validate(row.chunk_metadata)
            chunks.append(
                DocumentChunk(
                    chunk_id=row.chunk_id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    metadata=metadata,
                )
            )

        return chunks

    def search_chunks(
        self,
        *,
        knowledge_base_ids: list[str],
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not knowledge_base_ids:
            raise ValueError("knowledge_base_ids must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        query_vector = embed_checked(
            self._embedding_provider,
            [query],
        )[0]
        distance_expression = ChunkRow.embedding.cosine_distance(query_vector).label("distance")

        statement = (
            select(ChunkRow, distance_expression)
            .where(ChunkRow.knowledge_base_id.in_(knowledge_base_ids))
            .order_by(
                distance_expression,
                ChunkRow.chunk_id,
            )
            .limit(top_k)
        )
        rows = self._session.execute(statement).all()
        results: list[RetrievedChunk] = []

        for row, distance_value in rows:
            results.append(
                RetrievedChunk(
                    chunk_id=row.chunk_id,
                    source_id=row.source_id,
                    knowledge_base_id=row.knowledge_base_id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    distance=float(distance_value),
                )
            )

        return results
