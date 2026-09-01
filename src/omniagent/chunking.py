import hashlib
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniagent.ingestion import ParsedDocument


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_size: int = Field(gt=0)
    overlap: int = Field(ge=0)
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        return self


class TextChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class ChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    knowledge_base_id: str
    source_name: str
    checksum: str
    parser_version: str
    chunking_version: str
    chunk_size: int
    overlap: int
    unit_index: int
    page_number: int | None
    section: str | None
    char_start: int
    char_end: int


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(pattern=r"^chk-[0-9a-f]{64}$")
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    metadata: ChunkMetadata


def chunk_text(
    text: str,
    config: ChunkingConfig,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    if text == "":
        return chunks
    for start in range(0, len(text), config.chunk_size - config.overlap):
        end = min(start + config.chunk_size, len(text))
        chunks.append(
            TextChunk(
                char_end=end,
                char_start=start,
                content=text[start:end],
            )
        )
        if end == len(text):
            break
    return chunks


def _build_chunk_id(
    *,
    document: ParsedDocument,
    config: ChunkingConfig,
    char_start: int,
    char_end: int,
    content: str,
) -> str:
    identity = "\x1f".join(
        (
            document.source_id,
            document.checksum,
            document.parser_version,
            config.version,
            str(config.chunk_size),
            str(config.overlap),
            str(char_start),
            str(char_end),
            content,
        )
    )
    return f"chk-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def chunk_document(
    document: ParsedDocument,
    config: ChunkingConfig,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []

    for unit in document.units:
        for text_chunk in chunk_text(unit.content, config):
            char_start = unit.char_start + text_chunk.char_start
            char_end = unit.char_start + text_chunk.char_end
            chunks.append(
                DocumentChunk(
                    chunk_id=_build_chunk_id(
                        document=document,
                        config=config,
                        char_start=char_start,
                        char_end=char_end,
                        content=text_chunk.content,
                    ),
                    chunk_index=len(chunks),
                    content=text_chunk.content,
                    metadata=ChunkMetadata(
                        source_id=document.source_id,
                        knowledge_base_id=document.knowledge_base_id,
                        source_name=document.source_name,
                        checksum=document.checksum,
                        parser_version=document.parser_version,
                        chunking_version=config.version,
                        chunk_size=config.chunk_size,
                        overlap=config.overlap,
                        unit_index=unit.unit_index,
                        page_number=unit.page_number,
                        section=unit.section,
                        char_start=char_start,
                        char_end=char_end,
                    ),
                )
            )

    return chunks
