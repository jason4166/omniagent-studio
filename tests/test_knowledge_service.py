from omniagent.chunking import ChunkingConfig
from omniagent.profiles import KnowledgeBase
from omniagent.repositories import InMemoryKnowledgeRepository
from omniagent.services import KnowledgeBaseService


def test_config_change_rebuilds_chunks_and_preserves_original_source() -> None:
    repository = InMemoryKnowledgeRepository()
    raw_bytes = b"Synthetic policy text long enough for several chunks."
    first_service = KnowledgeBaseService(
        repository,
        ChunkingConfig(chunk_size=20, overlap=5, version="test-v1"),
    )
    first_service.create(KnowledgeBase(knowledge_base_id="kb-demo", name="Synthetic Demo"))

    imported = first_service.import_source(
        knowledge_base_id="kb-demo",
        source_name="policy.txt",
        mime_type="text/plain",
        raw_bytes=raw_bytes,
    )
    assert imported.source_id is not None
    first_source = repository.get_source(imported.source_id)
    first_ids = [chunk.chunk_id for chunk in repository.list_chunks(imported.source_id)]

    second_service = KnowledgeBaseService(
        repository,
        ChunkingConfig(chunk_size=16, overlap=4, version="test-v2"),
    )
    rebuilt = second_service.import_source(
        knowledge_base_id="kb-demo",
        source_name="policy.txt",
        mime_type="text/plain",
        raw_bytes=raw_bytes,
    )
    second_ids = [chunk.chunk_id for chunk in repository.list_chunks(imported.source_id)]

    assert rebuilt.status == "rebuilt"
    assert rebuilt.source_id == imported.source_id
    assert repository.get_source(imported.source_id) is first_source
    assert repository.get_source_bytes(imported.source_id) == raw_bytes
    assert first_ids != second_ids
    assert all(
        chunk.metadata.chunking_version == "test-v2"
        for chunk in repository.list_chunks(imported.source_id)
    )


def test_same_source_and_config_returns_duplicate() -> None:
    repository = InMemoryKnowledgeRepository()
    service = KnowledgeBaseService(
        repository,
        ChunkingConfig(chunk_size=20, overlap=5, version="test-v1"),
    )
    service.create(KnowledgeBase(knowledge_base_id="kb-demo", name="Synthetic Demo"))
    first = service.import_source(
        knowledge_base_id="kb-demo",
        source_name="policy.txt",
        mime_type="text/plain",
        raw_bytes=b"Synthetic policy text.",
    )
    second = service.import_source(
        knowledge_base_id="kb-demo",
        source_name="policy.txt",
        mime_type="text/plain",
        raw_bytes=b"Synthetic policy text.",
    )

    assert first.status == "imported"
    assert second.status == "duplicate"
    assert first.source_id == second.source_id
    assert first.chunk_count == second.chunk_count
