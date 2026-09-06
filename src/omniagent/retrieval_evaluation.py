import json
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from omniagent.chunking import ChunkingConfig, DocumentChunk, chunk_document
from omniagent.ingestion import (
    DocumentParseError,
    ParsedDocument,
    build_source_id,
    checksum_bytes,
    parse_markdown,
)
from omniagent.retrieval import RetrievalHit, TextQueryOperator
from omniagent.retrieval_metrics import calculate_recall_at_k, calculate_reciprocal_rank

RetrievalEvalCategory = Literal[
    "exact_name",
    "abbreviation",
    "paraphrase",
    "long_chinese",
    "no_answer",
    "cross_kb",
]
RetrievalMode = Literal["vector", "text", "hybrid"]


class RetrievalEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    category: RetrievalEvalCategory
    authorized_knowledge_base_ids: tuple[str, ...] = Field(min_length=1)
    relevant_chunk_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if not self.query.strip():
            raise ValueError("query must not be blank")

        if any(
            not knowledge_base_id.strip()
            for knowledge_base_id in self.authorized_knowledge_base_ids
        ):
            raise ValueError("authorized knowledge base IDs must not be blank")
        if len(self.authorized_knowledge_base_ids) != len(set(self.authorized_knowledge_base_ids)):
            raise ValueError("authorized knowledge base IDs must be unique")

        if any(not chunk_id.strip() for chunk_id in self.relevant_chunk_ids):
            raise ValueError("relevant chunk IDs must not be blank")
        if len(self.relevant_chunk_ids) != len(set(self.relevant_chunk_ids)):
            raise ValueError("relevant chunk IDs must be unique")

        if self.category == "no_answer" and self.relevant_chunk_ids:
            raise ValueError("no-answer cases must not contain relevant chunk IDs")
        if self.category != "no_answer" and not self.relevant_chunk_ids:
            raise ValueError("answerable cases must contain relevant chunk IDs")

        return self


class RetrievalHitsProvider(Protocol):
    def retrieve_hits(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> list[RetrievalHit]: ...


class RetrievalEvalContractError(RuntimeError):
    pass


class RetrievalEvalSafetyError(RuntimeError):
    pass


class RetrievalEvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    category: RetrievalEvalCategory
    retrieval_mode: RetrievalMode
    authorized_knowledge_base_ids: tuple[str, ...] = Field(min_length=1)
    relevant_chunk_ids: tuple[str, ...]
    hits: tuple[RetrievalHit, ...]
    recall_at_1: float | None = Field(default=None, ge=0.0, le=1.0)
    recall_at_3: float | None = Field(default=None, ge=0.0, le=1.0)
    recall_at_5: float | None = Field(default=None, ge=0.0, le=1.0)
    reciprocal_rank: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_metric_presence(self) -> Self:
        metrics = (
            self.recall_at_1,
            self.recall_at_3,
            self.recall_at_5,
            self.reciprocal_rank,
        )
        if self.category == "no_answer" and any(metric is not None for metric in metrics):
            raise ValueError("no-answer results must not contain answerable metrics")
        if self.category != "no_answer" and any(metric is None for metric in metrics):
            raise ValueError("answerable results require Recall and reciprocal rank")
        return self

    @property
    def retrieved_chunk_ids(self) -> tuple[str, ...]:
        return tuple(hit.chunk_id for hit in self.hits)


class RetrievalEvalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retrieval_mode: RetrievalMode
    case_count: int = Field(gt=0)
    answerable_case_count: int = Field(gt=0)
    no_answer_case_count: int = Field(ge=0)
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    no_answer_empty_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_counts_and_no_answer_rate(self) -> Self:
        if self.answerable_case_count + self.no_answer_case_count != self.case_count:
            raise ValueError("answerable and no-answer counts must equal case_count")
        if self.no_answer_case_count == 0 and self.no_answer_empty_rate is not None:
            raise ValueError("no-answer rate must be absent when there are no no-answer cases")
        if self.no_answer_case_count > 0 and self.no_answer_empty_rate is None:
            raise ValueError("no-answer rate is required when no-answer cases exist")
        return self


class RetrievalEvalRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    top_k: int = Field(gt=0)
    candidate_k: int = Field(gt=0)
    rank_constant: int = Field(ge=0)
    text_query_operator: TextQueryOperator = "and"

    @model_validator(mode="after")
    def validate_candidate_count(self) -> Self:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class RetrievalEvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_name: str = Field(min_length=1)
    created_at: AwareDatetime
    dataset_version: str = Field(pattern=r"^retrieval-v[1-9][0-9]*$")
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    embedding_dimension: int = Field(gt=0)
    corpus_chunk_count: int = Field(gt=0)
    config: RetrievalEvalRunConfig
    summaries: dict[RetrievalMode, RetrievalEvalSummary]
    results: dict[RetrievalMode, tuple[RetrievalEvalResult, ...]]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_mode_coverage(self) -> Self:
        required_modes: tuple[RetrievalMode, ...] = ("vector", "text", "hybrid")
        if set(self.summaries) != set(required_modes) or set(self.results) != set(required_modes):
            raise ValueError("report must contain vector, text, and hybrid results")
        for mode in required_modes:
            if self.summaries[mode].retrieval_mode != mode:
                raise ValueError("summary mode must match its report key")
            if any(result.retrieval_mode != mode for result in self.results[mode]):
                raise ValueError("result mode must match its report key")
        return self


def run_retrieval_eval(
    cases: list[RetrievalEvalCase],
    retriever: RetrievalHitsProvider,
    *,
    retrieval_mode: RetrievalMode,
) -> list[RetrievalEvalResult]:
    if not cases:
        raise ValueError("cases must not be empty")

    results: list[RetrievalEvalResult] = []

    for case in cases:
        hits = retriever.retrieve_hits(
            list(case.authorized_knowledge_base_ids),
            case.query,
        )
        retrieved_ids = [hit.chunk_id for hit in hits]

        if len(retrieved_ids) != len(set(retrieved_ids)):
            raise RetrievalEvalContractError(
                f"retriever returned duplicate chunk IDs for case {case.case_id}"
            )

        expected_ranks = list(range(1, len(hits) + 1))
        if [hit.rank for hit in hits] != expected_ranks:
            raise RetrievalEvalContractError(
                f"retriever returned non-contiguous ranks for case {case.case_id}"
            )

        if any(hit.retrieval_mode != retrieval_mode for hit in hits):
            raise RetrievalEvalContractError(
                f"retriever returned a mismatched mode for case {case.case_id}"
            )

        unauthorized_ids = {
            hit.knowledge_base_id
            for hit in hits
            if hit.knowledge_base_id not in case.authorized_knowledge_base_ids
        }
        if unauthorized_ids:
            raise RetrievalEvalSafetyError(
                f"retriever returned unauthorized knowledge bases for case {case.case_id}"
            )

        metric_values: dict[str, float | None]
        if case.category == "no_answer":
            metric_values = {
                "recall_at_1": None,
                "recall_at_3": None,
                "recall_at_5": None,
                "reciprocal_rank": None,
            }
        else:
            relevant_ids = set(case.relevant_chunk_ids)
            metric_values = {
                "recall_at_1": calculate_recall_at_k(relevant_ids, retrieved_ids, 1),
                "recall_at_3": calculate_recall_at_k(relevant_ids, retrieved_ids, 3),
                "recall_at_5": calculate_recall_at_k(relevant_ids, retrieved_ids, 5),
                "reciprocal_rank": calculate_reciprocal_rank(relevant_ids, retrieved_ids),
            }

        results.append(
            RetrievalEvalResult(
                case_id=case.case_id,
                category=case.category,
                retrieval_mode=retrieval_mode,
                authorized_knowledge_base_ids=case.authorized_knowledge_base_ids,
                relevant_chunk_ids=case.relevant_chunk_ids,
                hits=tuple(hits),
                **metric_values,
            )
        )

    return results


def summarize_retrieval_eval(
    results: list[RetrievalEvalResult],
) -> RetrievalEvalSummary:
    if not results:
        raise ValueError("results must not be empty")

    case_ids = [result.case_id for result in results]
    if len(case_ids) != len(set(case_ids)):
        raise RetrievalEvalContractError("evaluation results must have unique case IDs")

    retrieval_modes = {result.retrieval_mode for result in results}
    if len(retrieval_modes) != 1:
        raise RetrievalEvalContractError("evaluation summary requires exactly one retrieval mode")

    answerable_results = [result for result in results if result.category != "no_answer"]
    no_answer_results = [result for result in results if result.category == "no_answer"]
    if not answerable_results:
        raise ValueError("at least one answerable result is required")

    def mean_metric(values: list[float | None], metric_name: str) -> float:
        if any(value is None for value in values):
            raise RetrievalEvalContractError(f"answerable result is missing metric {metric_name}")
        return sum(value for value in values if value is not None) / len(values)

    no_answer_empty_rate = (
        sum(not result.hits for result in no_answer_results) / len(no_answer_results)
        if no_answer_results
        else None
    )

    return RetrievalEvalSummary(
        retrieval_mode=results[0].retrieval_mode,
        case_count=len(results),
        answerable_case_count=len(answerable_results),
        no_answer_case_count=len(no_answer_results),
        recall_at_1=mean_metric(
            [result.recall_at_1 for result in answerable_results],
            "recall_at_1",
        ),
        recall_at_3=mean_metric(
            [result.recall_at_3 for result in answerable_results],
            "recall_at_3",
        ),
        recall_at_5=mean_metric(
            [result.recall_at_5 for result in answerable_results],
            "recall_at_5",
        ),
        mrr=mean_metric(
            [result.reciprocal_rank for result in answerable_results],
            "reciprocal_rank",
        ),
        no_answer_empty_rate=no_answer_empty_rate,
    )


class RetrievalEvalDatasetError(ValueError):
    pass


class RetrievalEvalKnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_base_id: str = Field(min_length=1)
    name: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_non_blank(self) -> Self:
        if not self.knowledge_base_id.strip() or not self.name.strip():
            raise ValueError("corpus knowledge base fields must not be blank")
        return self


class RetrievalEvalSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_base_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    relative_path: Path

    @model_validator(mode="after")
    def validate_markdown_source(self) -> Self:
        if (
            not self.knowledge_base_id.strip()
            or not self.source_name.strip()
            or not self.title.strip()
        ):
            raise ValueError("corpus source fields must not be blank")
        if Path(self.source_name).name != self.source_name:
            raise ValueError("corpus source_name must be a file name")
        if self.relative_path.is_absolute():
            raise ValueError("corpus source path must be relative")
        if self.relative_path.suffix.casefold() not in {".md", ".markdown"}:
            raise ValueError("retrieval evaluation corpus supports Markdown sources only")
        return self


class RetrievalEvalCorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str = Field(pattern=r"^retrieval-v[1-9][0-9]*$")
    chunking: ChunkingConfig
    knowledge_bases: tuple[RetrievalEvalKnowledgeBase, ...] = Field(min_length=1)
    sources: tuple[RetrievalEvalSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        knowledge_base_ids = [item.knowledge_base_id for item in self.knowledge_bases]
        if len(knowledge_base_ids) != len(set(knowledge_base_ids)):
            raise ValueError("corpus knowledge base IDs must be unique")

        source_paths = [source.relative_path for source in self.sources]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("corpus source paths must be unique")

        unknown_ids = {source.knowledge_base_id for source in self.sources} - set(
            knowledge_base_ids
        )
        if unknown_ids:
            raise ValueError("every corpus source must reference a declared knowledge base")

        return self


class PreparedRetrievalEvalSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_bytes: bytes
    document: ParsedDocument
    chunks: tuple[DocumentChunk, ...] = Field(min_length=1)


class PreparedRetrievalEvalCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: RetrievalEvalCorpusManifest
    sources: tuple[PreparedRetrievalEvalSource, ...] = Field(min_length=1)


def load_retrieval_eval_corpus(manifest_path: Path) -> PreparedRetrievalEvalCorpus:
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RetrievalEvalDatasetError("Retrieval corpus manifest could not be read") from exc
    except json.JSONDecodeError as exc:
        raise RetrievalEvalDatasetError("Invalid retrieval corpus manifest JSON") from exc

    try:
        manifest = RetrievalEvalCorpusManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        raise RetrievalEvalDatasetError("Invalid retrieval corpus manifest") from exc

    corpus_root = manifest_path.parent.resolve()
    prepared_sources: list[PreparedRetrievalEvalSource] = []

    for source in manifest.sources:
        source_path = (corpus_root / source.relative_path).resolve()
        if not source_path.is_relative_to(corpus_root):
            raise RetrievalEvalDatasetError("Corpus source path escapes the corpus directory")

        try:
            raw_bytes = source_path.read_bytes()
        except OSError as exc:
            raise RetrievalEvalDatasetError(
                f"Corpus source could not be read: {source.relative_path.as_posix()}"
            ) from exc

        checksum = checksum_bytes(raw_bytes)
        try:
            document = parse_markdown(
                raw_bytes=raw_bytes,
                source_id=build_source_id(
                    knowledge_base_id=source.knowledge_base_id,
                    source_name=source.source_name,
                    checksum=checksum,
                ),
                knowledge_base_id=source.knowledge_base_id,
                source_name=source.source_name,
                title=source.title,
            )
        except DocumentParseError as exc:
            raise RetrievalEvalDatasetError(
                f"Corpus source could not be parsed: {source.relative_path.as_posix()}"
            ) from exc
        chunks = chunk_document(document, manifest.chunking)
        prepared_sources.append(
            PreparedRetrievalEvalSource(
                raw_bytes=raw_bytes,
                document=document,
                chunks=tuple(chunks),
            )
        )

    return PreparedRetrievalEvalCorpus(
        manifest=manifest,
        sources=tuple(prepared_sources),
    )


def load_retrieval_eval_cases(path: Path) -> list[RetrievalEvalCase]:
    cases: list[RetrievalEvalCase] = []
    seen_case_ids: set[str] = set()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            raise RetrievalEvalDatasetError(f"Blank line at line {line_number}")

        try:
            raw_case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RetrievalEvalDatasetError(f"Invalid JSON at line {line_number}") from exc

        try:
            case = RetrievalEvalCase.model_validate(raw_case)
        except ValidationError as exc:
            raise RetrievalEvalDatasetError(
                f"Invalid RetrievalEvalCase at line {line_number}"
            ) from exc

        if case.case_id in seen_case_ids:
            raise RetrievalEvalDatasetError(
                f"Duplicate case_id at line {line_number}: {case.case_id}"
            )

        seen_case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise RetrievalEvalDatasetError("Retrieval evaluation dataset must not be empty")

    return cases
