from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TextQueryOperator = Literal["and", "or"]


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


class RetrievedTextChunk(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    chunk_id: str
    source_id: str
    knowledge_base_id: str
    chunk_index: int
    content: str
    text_score: float = Field(ge=0.0, allow_inf_nan=False)


class SourceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retrieval_mode: Literal["vector", "text", "hybrid"]
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    knowledge_base_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    rank: int = Field(ge=1)
    vector_rank: int | None = Field(default=None, ge=1)
    vector_distance: float | None = Field(default=None, allow_inf_nan=False)
    text_rank: int | None = Field(default=None, ge=1)
    text_score: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    final_score: float = Field(allow_inf_nan=False)
    source_locator: SourceLocator

    @model_validator(mode="after")
    def validate_mode_scores(self) -> Self:
        if (self.vector_rank is None) != (self.vector_distance is None):
            raise ValueError("vector_rank and vector_distance must appear together")
        if (self.text_rank is None) != (self.text_score is None):
            raise ValueError("text_rank and text_score must appear together")

        if self.retrieval_mode == "vector":
            if self.vector_rank is None or self.text_rank is not None:
                raise ValueError("vector hits require only vector rank and distance")
        elif self.retrieval_mode == "text":
            if self.text_rank is None or self.vector_rank is not None:
                raise ValueError("text hits require only text rank and score")
        elif self.vector_rank is None and self.text_rank is None:
            raise ValueError("hybrid hits require at least one source ranking")

        return self


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
