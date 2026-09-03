import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from omniagent.api import app
from omniagent.chunking import ChunkingConfig, DocumentChunk, chunk_document
from omniagent.database import build_engine, build_session_factory
from omniagent.db_models import AgentProfileRow, ChunkRow, PromptVersionRow, SourceRow
from omniagent.embeddings import EMBEDDING_DIMENSION, EmbeddingValidationError, FakeEmbedding
from omniagent.ingestion import ParsedDocument, build_source_id, checksum_bytes, parse_txt
from omniagent.postgres_repositories import (
    SqlAlchemyAgentProfileRepository,
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyPromptVersionRepository,
    SqlAlchemyToolDefinitionRepository,
)
from omniagent.postgres_retrieval import PgVectorRetriever
from omniagent.profiles import AgentProfile, AgentProfilePatch, KnowledgeBase
from omniagent.prompts import PromptVersionAlreadyExistsError, PromptVersionService
from omniagent.services import AgentProfileService, KnowledgeBaseService
from omniagent.tooling import ToolDefinition, ToolRisk

TEST_DATABASE_URL = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")


class WrongCountEmbedding:
    model_name = "wrong-count"
    dimension = EMBEDDING_DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return []


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if TEST_DATABASE_URL is None:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL is not configured")

    engine = build_engine(TEST_DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def postgres_session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def build_document_and_chunks(
    *,
    knowledge_base_id: str,
    source_name: str,
    content: str,
) -> tuple[bytes, ParsedDocument, list[DocumentChunk]]:
    raw_bytes = content.encode("utf-8")
    checksum = checksum_bytes(raw_bytes)
    source_id = build_source_id(
        knowledge_base_id=knowledge_base_id,
        source_name=source_name,
        checksum=checksum,
    )
    document = parse_txt(
        raw_bytes=raw_bytes,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        source_name=source_name,
        title=source_name,
    )
    chunks = chunk_document(
        document,
        ChunkingConfig(
            chunk_size=200,
            overlap=0,
            version="day11-postgres-test",
        ),
    )
    return raw_bytes, document, chunks


def test_source_and_chunks_round_trip_through_domain_models(
    postgres_session: Session,
) -> None:
    knowledge_base_id = f"kb-roundtrip-{uuid4().hex}"
    raw_bytes, document, chunks = build_document_and_chunks(
        knowledge_base_id=knowledge_base_id,
        source_name="refunds.txt",
        content="Refunds are available within thirty days.",
    )
    repository = SqlAlchemyKnowledgeRepository(postgres_session, FakeEmbedding())

    repository.save_knowledge_base(
        KnowledgeBase(knowledge_base_id=knowledge_base_id, name="Round Trip")
    )
    repository.save_source(document, raw_bytes)
    repository.save_chunks(document.source_id, chunks)
    postgres_session.flush()

    assert repository.get_source(document.source_id) == document
    assert repository.get_source_bytes(document.source_id) == raw_bytes
    assert repository.list_chunks(document.source_id) == chunks


def test_duplicate_import_does_not_duplicate_database_rows(
    postgres_session: Session,
) -> None:
    knowledge_base_id = f"kb-duplicate-{uuid4().hex}"
    repository = SqlAlchemyKnowledgeRepository(postgres_session, FakeEmbedding())
    service = KnowledgeBaseService(repository)
    service.create(
        KnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            name="Duplicate Import",
        )
    )

    first = service.import_source(
        knowledge_base_id=knowledge_base_id,
        source_name="refunds.txt",
        mime_type="text/plain",
        raw_bytes=b"Refunds are available within thirty days.",
    )
    second = service.import_source(
        knowledge_base_id=knowledge_base_id,
        source_name="refunds.txt",
        mime_type="text/plain",
        raw_bytes=b"Refunds are available within thirty days.",
    )
    postgres_session.flush()

    source_count = postgres_session.scalar(
        select(func.count())
        .select_from(SourceRow)
        .where(SourceRow.knowledge_base_id == knowledge_base_id)
    )
    chunk_count = postgres_session.scalar(
        select(func.count())
        .select_from(ChunkRow)
        .where(ChunkRow.knowledge_base_id == knowledge_base_id)
    )

    assert first.status == "imported"
    assert second.status == "duplicate"
    assert source_count == 1
    assert chunk_count == first.chunk_count


def test_failed_embedding_rolls_back_the_whole_import(postgres_engine: Engine) -> None:
    session_factory = build_session_factory(postgres_engine)
    knowledge_base_id = f"kb-rollback-{uuid4().hex}"

    with pytest.raises(EmbeddingValidationError):
        with session_factory.begin() as session:
            repository = SqlAlchemyKnowledgeRepository(session, WrongCountEmbedding())
            service = KnowledgeBaseService(repository)
            service.create(KnowledgeBase(knowledge_base_id=knowledge_base_id, name="Rollback Test"))
            service.import_source(
                knowledge_base_id=knowledge_base_id,
                source_name="refunds.txt",
                mime_type="text/plain",
                raw_bytes=b"Refunds are available within thirty days.",
            )

    with session_factory() as session:
        repository = SqlAlchemyKnowledgeRepository(session, FakeEmbedding())
        assert repository.get_knowledge_base(knowledge_base_id) is None


def test_vector_search_filters_namespace_before_top_k(
    postgres_session: Session,
) -> None:
    suffix = uuid4().hex
    sales_id = f"kb-sales-{suffix}"
    hr_id = f"kb-hr-{suffix}"
    sales = build_document_and_chunks(
        knowledge_base_id=sales_id,
        source_name="sales.txt",
        content="Sales refunds are available for thirty days.",
    )
    hr = build_document_and_chunks(
        knowledge_base_id=hr_id,
        source_name="hr.txt",
        content="Secret payroll policy",
    )
    repository = SqlAlchemyKnowledgeRepository(postgres_session, FakeEmbedding())
    repository.save_knowledge_base(KnowledgeBase(knowledge_base_id=sales_id, name="Sales"))
    repository.save_knowledge_base(KnowledgeBase(knowledge_base_id=hr_id, name="HR"))

    for raw_bytes, document, chunks in (sales, hr):
        repository.save_source(document, raw_bytes)
        repository.save_chunks(document.source_id, chunks)
    postgres_session.flush()

    sales_only = repository.search_chunks(
        knowledge_base_ids=[sales_id],
        query="Secret payroll policy",
        top_k=1,
    )
    both = repository.search_chunks(
        knowledge_base_ids=[sales_id, hr_id],
        query="Secret payroll policy",
        top_k=1,
    )

    assert [match.knowledge_base_id for match in sales_only] == [sales_id]
    assert [match.knowledge_base_id for match in both] == [hr_id]
    assert both[0].distance == pytest.approx(0.0)

    with pytest.raises(ValueError, match="knowledge_base_ids must not be empty"):
        repository.search_chunks(
            knowledge_base_ids=[],
            query="Secret payroll policy",
            top_k=1,
        )

    retriever_factory = sessionmaker(
        bind=postgres_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    retriever = PgVectorRetriever(
        retriever_factory,
        FakeEmbedding(),
        top_k=1,
    )
    assert retriever.retrieve([sales_id], "Secret payroll policy") == sales[1].content


def test_prompt_version_round_trip_and_rejects_overwrite(
    postgres_session: Session,
) -> None:
    prompt_version_id = f"prompt-test-{uuid4().hex}"
    repository = SqlAlchemyPromptVersionRepository(postgres_session)
    service = PromptVersionService(repository)

    created = service.create(
        prompt_version_id=prompt_version_id,
        content="You are helping {{customer_name}}.",
        created_at=datetime.now(UTC),
        variables=("customer_name",),
    )
    postgres_session.flush()
    postgres_session.expire_all()

    loaded = service.get(prompt_version_id)

    assert loaded == created

    with pytest.raises(PromptVersionAlreadyExistsError):
        service.create(
            prompt_version_id=prompt_version_id,
            content="This replacement must not be saved.",
            created_at=datetime.now(UTC),
        )


def test_tool_definition_round_trip_and_update(
    postgres_session: Session,
) -> None:
    tool_id = f"lookup-product-{uuid4().hex}"
    repository = SqlAlchemyToolDefinitionRepository(postgres_session)
    definition = ToolDefinition(
        name=tool_id,
        risk=ToolRisk.LOW,
        parameters_schema={
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
            "additionalProperties": False,
        },
        allowed_roles=("sales_member",),
        tags=["catalog"],
        requires_approval=False,
    )

    repository.save(definition)
    postgres_session.flush()
    postgres_session.expire_all()

    assert repository.get(tool_id) == definition

    updated = definition.model_copy(update={"tags": ["catalog", "read-only"]})
    repository.save(updated)
    postgres_session.flush()
    postgres_session.expire_all()

    assert repository.get(tool_id) == updated
    assert tool_id in [tool.name for tool in repository.list_all()]


def test_agent_profile_round_trip_and_update_associations(
    postgres_session: Session,
) -> None:
    suffix = uuid4().hex
    prompt_version_id = f"prompt-profile-{suffix}"
    knowledge_base_id = f"kb-profile-{suffix}"
    tool_id = f"tool-profile-{suffix}"
    profile_id = f"profile-{suffix}"

    prompt_service = PromptVersionService(SqlAlchemyPromptVersionRepository(postgres_session))
    prompt_service.create(
        prompt_version_id=prompt_version_id,
        content="You are a sales assistant.",
        created_at=datetime.now(UTC),
    )
    SqlAlchemyKnowledgeRepository(
        postgres_session,
        FakeEmbedding(),
    ).save_knowledge_base(
        KnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            name="Product Knowledge",
        )
    )
    SqlAlchemyToolDefinitionRepository(postgres_session).save(
        ToolDefinition(
            name=tool_id,
            risk=ToolRisk.LOW,
            requires_approval=False,
        )
    )
    postgres_session.flush()

    repository = SqlAlchemyAgentProfileRepository(postgres_session)
    service = AgentProfileService(repository)
    profile = AgentProfile(
        profile_id=profile_id,
        prompt_version_id=prompt_version_id,
        budget_policy_id="budget-standard",
        approval_policy_id="approval-standard",
        tool_ids=[tool_id],
        knowledge_base_ids=[knowledge_base_id],
    )

    service.create(profile)
    postgres_session.flush()
    postgres_session.expire_all()

    assert service.get(profile_id) == profile

    updated = service.update(
        profile_id,
        AgentProfilePatch(
            expected_version=1,
            tool_ids=[],
        ),
    )
    postgres_session.flush()
    postgres_session.expire_all()

    assert service.get(profile_id) == updated
    assert updated.version == 2
    assert updated.tool_ids == []
    assert updated.knowledge_base_ids == [knowledge_base_id]
    assert profile_id in [profile.profile_id for profile in repository.list_all()]


def test_api_uses_postgres_and_commits_across_requests(
    postgres_engine: Engine,
) -> None:
    suffix = uuid4().hex
    prompt_version_id = f"prompt-api-{suffix}"
    profile_id = f"profile-api-{suffix}"
    session_factory = build_session_factory(postgres_engine)

    with session_factory.begin() as session:
        PromptVersionService(SqlAlchemyPromptVersionRepository(session)).create(
            prompt_version_id=prompt_version_id,
            content="You are an API persistence test assistant.",
            created_at=datetime.now(UTC),
        )

    app.dependency_overrides.clear()
    try:
        payload = {
            "profile_id": profile_id,
            "prompt_version_id": prompt_version_id,
            "budget_policy_id": "budget-standard",
            "approval_policy_id": "approval-standard",
        }

        with TestClient(app) as client:
            create_response = client.post("/api/agents", json=payload)
            get_response = client.get(f"/api/agents/{profile_id}")

        assert create_response.status_code == 201
        assert get_response.status_code == 200
        assert get_response.json()["profile_id"] == profile_id

        with session_factory() as session:
            stored = SqlAlchemyAgentProfileRepository(session).get(profile_id)
            assert stored is not None
            assert stored.prompt_version_id == prompt_version_id
    finally:
        with session_factory.begin() as session:
            session.execute(delete(AgentProfileRow).where(AgentProfileRow.profile_id == profile_id))
            session.execute(
                delete(PromptVersionRow).where(
                    PromptVersionRow.prompt_version_id == prompt_version_id
                )
            )
