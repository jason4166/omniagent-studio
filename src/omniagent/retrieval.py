from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    chunk_id: str
    source_id: str
    knowledge_base_id: str
    chunk_index: int
    content: str
    distance: float = Field(allow_inf_nan=False)


class Retriever(Protocol):
    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str: ...


class FakeRetriever:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[tuple[tuple[str, ...], str]] = []

    def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> str:
        self.requests.append((tuple(knowledge_base_ids), query))
        return self.response
