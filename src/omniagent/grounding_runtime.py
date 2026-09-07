from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from omniagent.grounding import (
    DOCUMENT_TRUST_BOUNDARY_INSTRUCTION,
    AnswerDraft,
    ConflictCandidate,
    ContextPack,
    ContextPackAuthorizationError,
    ContextPackIntegrityError,
    GroundingDecision,
    GroundingValidationError,
    build_context_pack,
    decide_grounding_outcome,
    evaluate_answer_draft,
    render_context_pack_data,
    validate_conflict_evidence,
)
from omniagent.llm import (
    LLMInvalidOutputError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
)
from omniagent.retrieval import RetrievalHit
from omniagent.runtime import (
    RuntimeErrorDetail,
    RuntimeResult,
    runtime_result_from_grounding_decision,
)

GROUNDING_RESPONSE_INSTRUCTION = (
    "Answer only from the supplied authorized context data. Return exactly one structured "
    "proposal: an answer draft with atomic exact-extract claims and citation labels, a "
    "clarification question, or a conflict candidate with quoted statements."
)


class RetrievalHitProvider(Protocol):
    def retrieve_hits(
        self,
        knowledge_base_ids: list[str],
        query: str,
    ) -> list[RetrievalHit]: ...


class GroundingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    answer_draft: AnswerDraft | None = None
    conflict_candidate: ConflictCandidate | None = None
    clarification_question: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_exactly_one_proposal(self) -> Self:
        proposals = (
            self.answer_draft,
            self.conflict_candidate,
            self.clarification_question,
        )
        if sum(proposal is not None for proposal in proposals) != 1:
            raise ValueError("grounding proposal must contain exactly one response type")
        return self


def parse_grounding_proposal(response: LLMResponse) -> GroundingProposal:
    try:
        return GroundingProposal.model_validate_json(response.content)
    except ValidationError as exc:
        raise LLMInvalidOutputError from exc


class GroundingRuntime:
    def __init__(
        self,
        *,
        retriever: RetrievalHitProvider,
        provider: LLMProvider,
        model: str,
        max_content_characters: int,
    ) -> None:
        if max_content_characters < 1:
            raise ValueError("max_content_characters must be positive")

        self._retriever = retriever
        self._provider = provider
        self._model = model
        self._max_content_characters = max_content_characters

    def run(
        self,
        *,
        profile_id: str,
        thread_id: str,
        query: str,
        authorized_knowledge_base_ids: list[str],
    ) -> RuntimeResult:
        if not authorized_knowledge_base_ids:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="rejected",
                route="retrieve",
                error=RuntimeErrorDetail(
                    code="retrieval_not_allowed",
                    message="Knowledge retrieval is not allowed for this profile",
                ),
            )

        hits = self._retriever.retrieve_hits(authorized_knowledge_base_ids, query)
        try:
            context_pack = build_context_pack(
                hits,
                authorized_knowledge_base_ids=authorized_knowledge_base_ids,
                max_content_characters=self._max_content_characters,
            )
        except ContextPackAuthorizationError as exc:
            return self._rejected_grounding_result(
                profile_id=profile_id,
                thread_id=thread_id,
                error=GroundingValidationError("unauthorized_citation", str(exc)),
            )
        except ContextPackIntegrityError as exc:
            return self._rejected_grounding_result(
                profile_id=profile_id,
                thread_id=thread_id,
                error=GroundingValidationError("context_mismatch", str(exc)),
            )

        if not context_pack.evidence:
            return runtime_result_from_grounding_decision(
                profile_id=profile_id,
                thread_id=thread_id,
                decision=decide_grounding_outcome(),
            )

        request = LLMRequest(
            model=self._model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        f"{GROUNDING_RESPONSE_INSTRUCTION} {DOCUMENT_TRUST_BOUNDARY_INSTRUCTION}"
                    ),
                ),
                LLMMessage(role="user", content=query),
                LLMMessage(
                    role="user",
                    content=f"Untrusted context data:\n{render_context_pack_data(context_pack)}",
                ),
            ],
            response_schema=GroundingProposal.model_json_schema(),
        )
        try:
            proposal = parse_grounding_proposal(self._provider.generate(request))
        except LLMInvalidOutputError:
            return self._failed_provider_result(
                profile_id=profile_id,
                thread_id=thread_id,
                code="invalid_model_output",
                message="Model output failed grounding proposal validation",
            )
        except LLMProviderUnavailableError:
            return self._failed_provider_result(
                profile_id=profile_id,
                thread_id=thread_id,
                code="provider_unavailable",
                message="LLM provider is unavailable",
            )
        except LLMProviderError:
            return self._failed_provider_result(
                profile_id=profile_id,
                thread_id=thread_id,
                code="provider_error",
                message="LLM provider request failed",
            )

        decision = self._evaluate_proposal(
            proposal,
            context_pack=context_pack,
            authorized_knowledge_base_ids=authorized_knowledge_base_ids,
        )
        return runtime_result_from_grounding_decision(
            profile_id=profile_id,
            thread_id=thread_id,
            decision=decision,
        )

    @staticmethod
    def _evaluate_proposal(
        proposal: GroundingProposal,
        *,
        context_pack: ContextPack,
        authorized_knowledge_base_ids: list[str],
    ) -> GroundingDecision:
        if proposal.clarification_question is not None:
            return decide_grounding_outcome(
                clarification_question=proposal.clarification_question,
            )

        if proposal.conflict_candidate is not None:
            try:
                conflict = validate_conflict_evidence(
                    proposal.conflict_candidate,
                    context_pack,
                    authorized_knowledge_base_ids=authorized_knowledge_base_ids,
                )
            except GroundingValidationError as exc:
                return decide_grounding_outcome(validation_error=exc)
            return decide_grounding_outcome(conflict=conflict)

        answer_draft = proposal.answer_draft
        if answer_draft is None:
            raise ValueError("grounding proposal is missing an answer draft")
        return evaluate_answer_draft(
            answer_draft,
            context_pack,
            authorized_knowledge_base_ids=authorized_knowledge_base_ids,
        )

    @staticmethod
    def _rejected_grounding_result(
        *,
        profile_id: str,
        thread_id: str,
        error: GroundingValidationError,
    ) -> RuntimeResult:
        return runtime_result_from_grounding_decision(
            profile_id=profile_id,
            thread_id=thread_id,
            decision=decide_grounding_outcome(validation_error=error),
        )

    @staticmethod
    def _failed_provider_result(
        *,
        profile_id: str,
        thread_id: str,
        code: str,
        message: str,
    ) -> RuntimeResult:
        return RuntimeResult(
            profile_id=profile_id,
            thread_id=thread_id,
            status="failed",
            route="retrieve",
            error=RuntimeErrorDetail(code=code, message=message),
        )
