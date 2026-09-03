from typing import Protocol

from omniagent.chunking import DocumentChunk
from omniagent.ingestion import ParsedDocument
from omniagent.profiles import AgentProfile, KnowledgeBase
from omniagent.tooling import ToolDefinition


class AgentProfileRepository(Protocol):
    def get(self, profile_id: str) -> AgentProfile | None: ...

    def save(self, profile: AgentProfile) -> None: ...

    def list_all(self) -> list[AgentProfile]: ...


class InMemoryAgentProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}

    def get(self, profile_id: str) -> AgentProfile | None:
        return self._profiles.get(profile_id)

    def save(self, profile: AgentProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def list_all(self) -> list[AgentProfile]:
        return list(self._profiles.values())


class ToolDefinitionRepository(Protocol):
    def get(self, tool_id: str) -> ToolDefinition | None: ...

    def save(self, definition: ToolDefinition) -> None: ...

    def list_all(self) -> list[ToolDefinition]: ...


class InMemoryToolDefinitionRepository:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._definitions.get(tool_id)

    def save(self, definition: ToolDefinition) -> None:
        self._definitions[definition.name] = definition

    def list_all(self) -> list[ToolDefinition]:
        return list(self._definitions.values())


class KnowledgeRepository(Protocol):
    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None: ...

    def save_knowledge_base(self, knowledge_base: KnowledgeBase) -> None: ...

    def get_source(self, source_id: str) -> ParsedDocument | None: ...

    def save_source(self, document: ParsedDocument, raw_bytes: bytes) -> None: ...

    def get_source_bytes(self, source_id: str) -> bytes | None: ...

    def save_chunks(self, source_id: str, chunks: list[DocumentChunk]) -> None: ...

    def list_chunks(self, source_id: str) -> list[DocumentChunk]: ...


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self._knowledge_bases: dict[str, KnowledgeBase] = {}
        self._sources: dict[str, ParsedDocument] = {}
        self._source_bytes: dict[str, bytes] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}

    def get_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase | None:
        return self._knowledge_bases.get(knowledge_base_id)

    def save_knowledge_base(self, knowledge_base: KnowledgeBase) -> None:
        self._knowledge_bases[knowledge_base.knowledge_base_id] = knowledge_base

    def get_source(self, source_id: str) -> ParsedDocument | None:
        return self._sources.get(source_id)

    def save_source(self, document: ParsedDocument, raw_bytes: bytes) -> None:
        self._sources[document.source_id] = document
        self._source_bytes[document.source_id] = raw_bytes

    def get_source_bytes(self, source_id: str) -> bytes | None:
        return self._source_bytes.get(source_id)

    def save_chunks(self, source_id: str, chunks: list[DocumentChunk]) -> None:
        self._chunks[source_id] = list(chunks)

    def list_chunks(self, source_id: str) -> list[DocumentChunk]:
        return list(self._chunks.get(source_id, []))
