import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from omniagent.grounding import (
    AnswerDraft,
    CitationResolutionError,
    ConflictCandidate,
    ContextPack,
    ContextPackAuthorizationError,
    ContextPackIntegrityError,
    GroundingDecision,
    GroundingDecisionFailureCode,
    GroundingValidationError,
    build_context_pack,
    decide_grounding_outcome,
    evaluate_answer_draft,
    resolve_citation,
    validate_answer_citations,
    validate_conflict_evidence,
    validate_exact_claim_support,
)
from omniagent.retrieval import RetrievalHit, SourceLocator

GroundingEvalCategory = Literal[
    "normal",
    "multi_source",
    "missing_citation",
    "wrong_id",
    "unauthorized_id",
    "no_answer",
    "fabricated_claim",
    "document_injection",
    "overlong_context",
    "clarification",
    "conflict",
]
GroundingOutcome = Literal["answer", "clarify", "abstain", "conflict"]
GROUNDING_EVAL_LIMITATIONS = (
    "Claim support uses deterministic exact extracts; it does not score semantic paraphrases.",
    "The frozen suite is synthetic and does not measure a real LLM or embedding provider.",
    "Citation and claim rates include intentional negative cases and are not validator accuracy.",
)


class GroundingEvalHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    knowledge_base_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_locator: SourceLocator


class GroundingEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    case_id: str = Field(pattern=r"^grounding-[0-9]{3}$")
    query: str = Field(min_length=1)
    category: GroundingEvalCategory
    authorized_knowledge_base_ids: tuple[str, ...] = Field(min_length=1)
    max_content_characters: int = Field(gt=0)
    hits: tuple[GroundingEvalHit, ...] = ()
    answer_draft: AnswerDraft
    conflict_candidate: ConflictCandidate | None = None
    clarification_question: str | None = None
    expected_outcome: GroundingOutcome
    expected_failure_code: GroundingDecisionFailureCode | None = None

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        authorized_ids = self.authorized_knowledge_base_ids
        if any(not knowledge_base_id.strip() for knowledge_base_id in authorized_ids):
            raise ValueError("authorized knowledge base IDs must not be blank")
        if len(authorized_ids) != len(set(authorized_ids)):
            raise ValueError("authorized knowledge base IDs must be unique")

        if self.expected_outcome == "abstain":
            if self.expected_failure_code is None:
                raise ValueError("abstain cases require an expected failure code")
        elif self.expected_failure_code is not None:
            raise ValueError("only abstain cases may have an expected failure code")

        if self.expected_outcome == "conflict" and self.conflict_candidate is None:
            raise ValueError("conflict cases require a conflict candidate")
        if self.conflict_candidate is not None and self.expected_outcome not in (
            "conflict",
            "abstain",
        ):
            raise ValueError("conflict candidates are only valid for conflict or abstain cases")
        if (self.expected_outcome == "clarify") != (self.clarification_question is not None):
            raise ValueError("clarification question must appear only for clarify cases")

        return self


class GroundingEvalDatasetError(ValueError):
    pass


class GroundingEvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    category: GroundingEvalCategory
    expected_outcome: GroundingOutcome
    actual_outcome: GroundingOutcome
    expected_failure_code: GroundingDecisionFailureCode | None
    actual_failure_code: GroundingDecisionFailureCode | None
    outcome_correct: bool
    decision_correct: bool
    attempted_citation_count: int = Field(ge=0)
    valid_citation_count: int = Field(ge=0)
    evaluated_claim_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    decision: GroundingDecision

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.valid_citation_count > self.attempted_citation_count:
            raise ValueError("valid citations cannot exceed attempted citations")
        if self.supported_claim_count > self.evaluated_claim_count:
            raise ValueError("supported claims cannot exceed evaluated claims")
        return self


class GroundingEvalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_count: int = Field(gt=0)
    correct_outcome_count: int = Field(ge=0)
    correct_decision_count: int = Field(ge=0)
    attempted_citation_count: int = Field(ge=0)
    valid_citation_count: int = Field(ge=0)
    evaluated_claim_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    expected_abstention_count: int = Field(ge=0)
    correct_abstention_count: int = Field(ge=0)
    outcome_accuracy: float = Field(ge=0.0, le=1.0)
    decision_accuracy: float = Field(ge=0.0, le=1.0)
    citation_validity_rate: float = Field(ge=0.0, le=1.0)
    claim_support_rate: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    abstention_accuracy: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_summary_counts(self) -> Self:
        if self.correct_outcome_count > self.case_count:
            raise ValueError("correct outcomes cannot exceed cases")
        if self.correct_decision_count > self.case_count:
            raise ValueError("correct decisions cannot exceed cases")
        if self.valid_citation_count > self.attempted_citation_count:
            raise ValueError("valid citations cannot exceed attempted citations")
        if self.supported_claim_count + self.unsupported_claim_count != self.evaluated_claim_count:
            raise ValueError("supported and unsupported claims must cover evaluated claims")
        if self.correct_abstention_count > self.case_count:
            raise ValueError("correct abstention classifications cannot exceed cases")
        return self


class GroundingEvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created_at: AwareDatetime
    dataset_version: Literal["grounding-v1"] = "grounding-v1"
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: GroundingEvalSummary
    results: tuple[GroundingEvalResult, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report_case_count(self) -> Self:
        if len(self.results) != self.summary.case_count:
            raise ValueError("report results must match summary case count")
        return self


REQUIRED_GROUNDING_CATEGORIES = frozenset(
    {
        "normal",
        "multi_source",
        "wrong_id",
        "unauthorized_id",
        "no_answer",
        "fabricated_claim",
        "document_injection",
        "overlong_context",
        "clarification",
        "conflict",
    }
)


def load_grounding_eval_cases(path: Path) -> list[GroundingEvalCase]:
    cases: list[GroundingEvalCase] = []
    seen_case_ids: set[str] = set()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            raise GroundingEvalDatasetError(f"Blank line at line {line_number}")

        try:
            raw_case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GroundingEvalDatasetError(f"Invalid JSON at line {line_number}") from exc

        try:
            case = GroundingEvalCase.model_validate(raw_case)
        except ValidationError as exc:
            raise GroundingEvalDatasetError(
                f"Invalid GroundingEvalCase at line {line_number}"
            ) from exc

        if case.case_id in seen_case_ids:
            raise GroundingEvalDatasetError(
                f"Duplicate case_id at line {line_number}: {case.case_id}"
            )

        seen_case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise GroundingEvalDatasetError("Grounding evaluation dataset must not be empty")

    return cases


def validate_grounding_eval_suite(cases: list[GroundingEvalCase]) -> None:
    if len(cases) < 12:
        raise GroundingEvalDatasetError("Grounding evaluation suite requires at least 12 cases")

    categories = {case.category for case in cases}
    missing_categories = REQUIRED_GROUNDING_CATEGORIES - categories
    if missing_categories:
        missing = ", ".join(sorted(missing_categories))
        raise GroundingEvalDatasetError(f"Grounding evaluation suite is missing: {missing}")


def _to_retrieval_hit(hit: GroundingEvalHit) -> RetrievalHit:
    return RetrievalHit(
        retrieval_mode="vector",
        chunk_id=hit.chunk_id,
        source_id=hit.source_id,
        knowledge_base_id=hit.knowledge_base_id,
        chunk_index=hit.rank - 1,
        content=hit.content,
        rank=hit.rank,
        vector_rank=hit.rank,
        vector_distance=0.0,
        final_score=1.0,
        source_locator=hit.source_locator,
    )


def _build_eval_context(case: GroundingEvalCase) -> ContextPack:
    return build_context_pack(
        [_to_retrieval_hit(hit) for hit in case.hits],
        authorized_knowledge_base_ids=case.authorized_knowledge_base_ids,
        max_content_characters=case.max_content_characters,
    )


def _evaluate_case_decision(
    case: GroundingEvalCase,
    context_pack: ContextPack,
) -> GroundingDecision:
    if case.conflict_candidate is not None:
        try:
            conflict = validate_conflict_evidence(
                case.conflict_candidate,
                context_pack,
                authorized_knowledge_base_ids=case.authorized_knowledge_base_ids,
            )
        except GroundingValidationError as exc:
            return decide_grounding_outcome(validation_error=exc)
        return decide_grounding_outcome(conflict=conflict)

    if case.clarification_question is not None:
        return decide_grounding_outcome(
            clarification_question=case.clarification_question,
        )

    return evaluate_answer_draft(
        case.answer_draft,
        context_pack,
        authorized_knowledge_base_ids=case.authorized_knowledge_base_ids,
    )


def _attempted_citation_labels(case: GroundingEvalCase) -> tuple[str, ...]:
    if case.conflict_candidate is not None:
        return tuple(statement.citation_label for statement in case.conflict_candidate.statements)
    if case.clarification_question is not None:
        return ()
    return tuple(
        citation_label
        for claim in case.answer_draft.claims
        for citation_label in claim.citation_labels
    )


def _count_valid_citations(
    labels: tuple[str, ...],
    context_pack: ContextPack | None,
    authorized_knowledge_base_ids: tuple[str, ...],
) -> int:
    if context_pack is None:
        return 0

    authorized_ids = set(authorized_knowledge_base_ids)
    valid_count = 0
    for label in labels:
        try:
            citation = resolve_citation(context_pack, label)
        except CitationResolutionError:
            continue
        if citation.knowledge_base_id in authorized_ids:
            valid_count += 1
    return valid_count


def _count_supported_claims(
    case: GroundingEvalCase,
    context_pack: ContextPack | None,
) -> tuple[int, int]:
    if case.conflict_candidate is not None or case.clarification_question is not None:
        return 0, 0

    evaluated_count = len(case.answer_draft.claims)
    if context_pack is None or not context_pack.evidence:
        return evaluated_count, 0

    supported_count = 0
    for claim in case.answer_draft.claims:
        single_claim_draft = AnswerDraft(claims=(claim,))
        try:
            citation_validated = validate_answer_citations(
                single_claim_draft,
                context_pack,
                authorized_knowledge_base_ids=case.authorized_knowledge_base_ids,
            )
            validate_exact_claim_support(citation_validated, context_pack)
        except GroundingValidationError:
            continue
        supported_count += 1

    return evaluated_count, supported_count


def run_grounding_eval_case(case: GroundingEvalCase) -> GroundingEvalResult:
    context_pack: ContextPack | None
    try:
        context_pack = _build_eval_context(case)
    except ContextPackAuthorizationError as exc:
        context_pack = None
        decision = decide_grounding_outcome(
            validation_error=GroundingValidationError(
                "unauthorized_citation",
                str(exc),
            )
        )
    except ContextPackIntegrityError as exc:
        context_pack = None
        decision = decide_grounding_outcome(
            validation_error=GroundingValidationError(
                "context_mismatch",
                str(exc),
            )
        )
    else:
        decision = _evaluate_case_decision(case, context_pack)

    attempted_labels = _attempted_citation_labels(case)
    evaluated_claim_count, supported_claim_count = _count_supported_claims(
        case,
        context_pack,
    )
    outcome_correct = decision.outcome == case.expected_outcome
    decision_correct = outcome_correct and decision.failure_code == case.expected_failure_code

    return GroundingEvalResult(
        case_id=case.case_id,
        category=case.category,
        expected_outcome=case.expected_outcome,
        actual_outcome=decision.outcome,
        expected_failure_code=case.expected_failure_code,
        actual_failure_code=decision.failure_code,
        outcome_correct=outcome_correct,
        decision_correct=decision_correct,
        attempted_citation_count=len(attempted_labels),
        valid_citation_count=_count_valid_citations(
            attempted_labels,
            context_pack,
            case.authorized_knowledge_base_ids,
        ),
        evaluated_claim_count=evaluated_claim_count,
        supported_claim_count=supported_claim_count,
        decision=decision,
    )


def summarize_grounding_eval(
    results: list[GroundingEvalResult],
) -> GroundingEvalSummary:
    if not results:
        raise ValueError("grounding evaluation results must not be empty")

    case_count = len(results)
    correct_outcome_count = sum(result.outcome_correct for result in results)
    correct_decision_count = sum(result.decision_correct for result in results)
    attempted_citation_count = sum(result.attempted_citation_count for result in results)
    valid_citation_count = sum(result.valid_citation_count for result in results)
    evaluated_claim_count = sum(result.evaluated_claim_count for result in results)
    supported_claim_count = sum(result.supported_claim_count for result in results)
    unsupported_claim_count = evaluated_claim_count - supported_claim_count
    expected_abstention_count = sum(result.expected_outcome == "abstain" for result in results)
    correct_abstention_count = sum(
        (result.expected_outcome == "abstain") == (result.actual_outcome == "abstain")
        for result in results
    )

    return GroundingEvalSummary(
        case_count=case_count,
        correct_outcome_count=correct_outcome_count,
        correct_decision_count=correct_decision_count,
        attempted_citation_count=attempted_citation_count,
        valid_citation_count=valid_citation_count,
        evaluated_claim_count=evaluated_claim_count,
        supported_claim_count=supported_claim_count,
        unsupported_claim_count=unsupported_claim_count,
        expected_abstention_count=expected_abstention_count,
        correct_abstention_count=correct_abstention_count,
        outcome_accuracy=correct_outcome_count / case_count,
        decision_accuracy=correct_decision_count / case_count,
        citation_validity_rate=valid_citation_count / attempted_citation_count,
        claim_support_rate=supported_claim_count / evaluated_claim_count,
        unsupported_claim_rate=unsupported_claim_count / evaluated_claim_count,
        abstention_accuracy=correct_abstention_count / case_count,
    )


def run_grounding_eval(cases: list[GroundingEvalCase]) -> GroundingEvalSummary:
    validate_grounding_eval_suite(cases)
    return summarize_grounding_eval([run_grounding_eval_case(case) for case in cases])


def compute_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_grounding_eval_report(dataset_path: Path) -> GroundingEvalReport:
    cases = load_grounding_eval_cases(dataset_path)
    validate_grounding_eval_suite(cases)
    results = tuple(run_grounding_eval_case(case) for case in cases)
    return GroundingEvalReport(
        created_at=datetime.now(UTC),
        dataset_sha256=compute_file_sha256(dataset_path),
        summary=summarize_grounding_eval(list(results)),
        results=results,
        limitations=GROUNDING_EVAL_LIMITATIONS,
    )


def build_grounding_eval_markdown(report: GroundingEvalReport) -> str:
    summary = report.summary
    lines = [
        "# Day 13 Grounding Evaluation",
        "",
        f"- Dataset: `{report.dataset_version}`",
        f"- Dataset SHA-256: `{report.dataset_sha256}`",
        f"- Cases: {summary.case_count}",
        "",
        "## Summary",
        "",
        "| Metric | Numerator | Denominator | Rate |",
        "|---|---:|---:|---:|",
        f"| Outcome accuracy | {summary.correct_outcome_count} | "
        f"{summary.case_count} | {summary.outcome_accuracy:.4f} |",
        f"| Decision accuracy | {summary.correct_decision_count} | "
        f"{summary.case_count} | {summary.decision_accuracy:.4f} |",
        f"| Citation validity | {summary.valid_citation_count} | "
        f"{summary.attempted_citation_count} | {summary.citation_validity_rate:.4f} |",
        f"| Claim support | {summary.supported_claim_count} | "
        f"{summary.evaluated_claim_count} | {summary.claim_support_rate:.4f} |",
        f"| Unsupported claims | {summary.unsupported_claim_count} | "
        f"{summary.evaluated_claim_count} | {summary.unsupported_claim_rate:.4f} |",
        f"| Abstention classification | {summary.correct_abstention_count} | "
        f"{summary.case_count} | {summary.abstention_accuracy:.4f} |",
        "",
        f"Expected abstentions: {summary.expected_abstention_count}.",
        "",
        "## Cases",
        "",
        "| Case | Category | Expected | Actual | Failure code | Decision correct |",
        "|---|---|---|---|---|---:|",
    ]

    for result in report.results:
        failure_code = result.actual_failure_code or "-"
        lines.append(
            f"| {result.case_id} | {result.category} | {result.expected_outcome} | "
            f"{result.actual_outcome} | {failure_code} | "
            f"{'yes' if result.decision_correct else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Citation validity and Claim support include deliberately invalid drafts. "
            "Use decision accuracy to determine whether the validator classified the frozen "
            "cases correctly.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines) + "\n"


def save_grounding_eval_report(
    report: GroundingEvalReport,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(f"{report.model_dump_json(indent=2)}\n", encoding="utf-8")
    markdown_path.write_text(build_grounding_eval_markdown(report), encoding="utf-8")
    return json_path, markdown_path
