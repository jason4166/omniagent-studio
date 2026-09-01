import pytest
from pydantic import ValidationError

from omniagent.chunking import ChunkingConfig, chunk_document, chunk_text
from omniagent.ingestion import ParsedDocument, build_source_id, checksum_bytes, parse_markdown


def parsed_markdown() -> ParsedDocument:
    raw_bytes = b"# Guide\n\nABCDEFGH\n\n## Warranty\n\nIJKLMNOP"
    checksum = checksum_bytes(raw_bytes)
    return parse_markdown(
        raw_bytes=raw_bytes,
        source_id=build_source_id(
            knowledge_base_id="kb-demo",
            source_name="guide.md",
            checksum=checksum,
        ),
        knowledge_base_id="kb-demo",
        source_name="guide.md",
        title="Guide",
    )


def test_chunking_config_requires_overlap_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError, match="overlap must be smaller"):
        ChunkingConfig(chunk_size=3, overlap=3, version="test-v1")


def test_chunk_text_applies_overlap_and_half_open_ranges() -> None:
    config = ChunkingConfig(chunk_size=3, overlap=1, version="test-v1")

    chunks = chunk_text("ABCDEFGH", config)

    assert [(chunk.char_start, chunk.char_end, chunk.content) for chunk in chunks] == [
        (0, 3, "ABC"),
        (2, 5, "CDE"),
        (4, 7, "EFG"),
        (6, 8, "GH"),
    ]


def test_chunk_text_returns_empty_list_for_empty_text() -> None:
    config = ChunkingConfig(chunk_size=3, overlap=1, version="test-v1")

    assert chunk_text("", config) == []


def test_extremely_long_text_is_bounded_by_chunk_size() -> None:
    config = ChunkingConfig(chunk_size=100, overlap=10, version="test-v1")

    chunks = chunk_text("A" * 1001, config)

    assert len(chunks) > 1
    assert max(len(chunk.content) for chunk in chunks) <= 100


def test_chunk_text_stops_after_first_chunk_reaches_end() -> None:
    config = ChunkingConfig(chunk_size=5, overlap=4, version="test-v1")

    chunks = chunk_text("ABCDEF", config)

    assert [(chunk.char_start, chunk.char_end) for chunk in chunks] == [(0, 5), (1, 6)]


def test_chunk_document_preserves_section_and_document_range() -> None:
    document = parsed_markdown()
    config = ChunkingConfig(chunk_size=5, overlap=1, version="test-v1")

    chunks = chunk_document(document, config)

    assert chunks[0].metadata.section == "Guide"
    assert chunks[-1].metadata.section == "Warranty"
    for chunk in chunks:
        start = chunk.metadata.char_start
        end = chunk.metadata.char_end
        assert document.content[start:end] == chunk.content


def test_chunk_document_never_crosses_semantic_unit_boundary() -> None:
    document = parsed_markdown()
    config = ChunkingConfig(chunk_size=20, overlap=2, version="test-v1")

    chunks = chunk_document(document, config)

    assert [chunk.content for chunk in chunks] == ["ABCDEFGH", "IJKLMNOP"]
    assert [chunk.metadata.unit_index for chunk in chunks] == [0, 1]


def test_chunk_ids_are_stable_for_same_document_and_config() -> None:
    document = parsed_markdown()
    config = ChunkingConfig(chunk_size=5, overlap=1, version="test-v1")

    first_ids = [chunk.chunk_id for chunk in chunk_document(document, config)]
    second_ids = [chunk.chunk_id for chunk in chunk_document(document, config)]

    assert first_ids == second_ids


def test_chunk_ids_change_when_chunking_config_changes() -> None:
    document = parsed_markdown()
    first_config = ChunkingConfig(chunk_size=5, overlap=1, version="test-v1")
    second_config = ChunkingConfig(chunk_size=6, overlap=2, version="test-v2")

    first_ids = [chunk.chunk_id for chunk in chunk_document(document, first_config)]
    second_ids = [chunk.chunk_id for chunk in chunk_document(document, second_config)]

    assert first_ids != second_ids


def test_repeated_content_keeps_distinct_source_locations() -> None:
    raw_bytes = b"# First\n\nSAME\n\n# Second\n\nSAME"
    document = parse_markdown(
        raw_bytes=raw_bytes,
        source_id=build_source_id(
            knowledge_base_id="kb-demo",
            source_name="repeated.md",
            checksum=checksum_bytes(raw_bytes),
        ),
        knowledge_base_id="kb-demo",
        source_name="repeated.md",
        title="Repeated",
    )
    config = ChunkingConfig(chunk_size=10, overlap=1, version="test-v1")

    chunks = chunk_document(document, config)

    assert [chunk.content for chunk in chunks] == ["SAME", "SAME"]
    assert chunks[0].metadata.char_start != chunks[1].metadata.char_start
    assert chunks[0].chunk_id != chunks[1].chunk_id
