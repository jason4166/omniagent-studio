from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniagent.llm import (
    LLMInvalidOutputError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRequest,
    RouteDecision,
    parse_route_decision,
)
from omniagent.profiles import AgentProfile
from omniagent.prompts import PromptRenderError, PromptVersionRepository, render_prompt
from omniagent.repositories import AgentProfileRepository
from omniagent.retrieval import Retriever
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import BudgetPolicy, ToolCall, ToolResult, generate_call_id


class RuntimeBudgetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_policy_id: str
    max_model_calls: int = Field(gt=0)
    max_tool_calls: int = Field(ge=0, le=1)
    max_steps: int = Field(gt=0)


class RuntimeConfigurationError(ValueError):
    pass


def validate_runtime_configuration(
    *,
    profiles: list[AgentProfile],
    prompt_repository: PromptVersionRepository,
    tool_registry: ToolRegistry,
    budget_policies: dict[str, RuntimeBudgetPolicy],
    knowledge_base_ids: set[str],
) -> None:
    for profile in profiles:
        if prompt_repository.get(profile.prompt_version_id) is None:
            raise RuntimeConfigurationError(
                f"Profile '{profile.profile_id}' references unknown prompt version "
                f"'{profile.prompt_version_id}'"
            )
        if profile.budget_policy_id not in budget_policies:
            raise RuntimeConfigurationError(
                f"Profile '{profile.profile_id}' references unknown budget policy "
                f"'{profile.budget_policy_id}'"
            )
        for tool_id in profile.tool_ids:
            if not tool_registry.has(tool_id):
                raise RuntimeConfigurationError(
                    f"Profile '{profile.profile_id}' references unregistered tool '{tool_id}'"
                )
        for knowledge_base_id in profile.knowledge_base_ids:
            if knowledge_base_id not in knowledge_base_ids:
                raise RuntimeConfigurationError(
                    f"Profile '{profile.profile_id}' references unknown knowledge base "
                    f"'{knowledge_base_id}'"
                )


class RuntimeErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RuntimeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    thread_id: str
    status: Literal["succeeded", "rejected", "failed"]
    route: Literal["direct", "retrieve", "tool", "clarify"] | None = None
    output_text: str | None = None
    tool_result: ToolResult | None = None
    error: RuntimeErrorDetail | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded result must not contain error")
        if self.status in ("rejected", "failed") and self.error is None:
            raise ValueError("rejected or failed result must contain error")
        if self.tool_result is not None and self.route != "tool":
            raise ValueError("tool_result requires tool route")
        return self


class AgentRuntime:
    def __init__(
        self,
        *,
        profile_repository: AgentProfileRepository,
        prompt_repository: PromptVersionRepository,
        provider: LLMProvider,
        actor_role: str,
        tool_registry: ToolRegistry,
        retriever: Retriever,
        budget_policies: dict[str, RuntimeBudgetPolicy],
        knowledge_base_ids: set[str],
        model: str,
    ) -> None:
        self._profile_repository = profile_repository
        self._prompt_repository = prompt_repository
        self._provider = provider
        self._actor_role = actor_role
        self._tool_registry = tool_registry
        self._retriever = retriever
        self._budget_policies = budget_policies
        self._knowledge_base_ids = knowledge_base_ids
        self._model = model

        validate_runtime_configuration(
            profiles=profile_repository.list_all(),
            prompt_repository=prompt_repository,
            tool_registry=tool_registry,
            budget_policies=budget_policies,
            knowledge_base_ids=knowledge_base_ids,
        )

    def run(
        self,
        profile_id: str,
        thread_id: str,
        message: str,
    ) -> RuntimeResult:
        profile = self._profile_repository.get(profile_id)

        if profile is None:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="rejected",
                error=RuntimeErrorDetail(
                    code="profile_not_found",
                    message="Agent profile was not found",
                ),
            )

        if not profile.enabled:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="rejected",
                error=RuntimeErrorDetail(
                    code="profile_disabled",
                    message="Agent profile is disabled",
                ),
            )

        budget_policy = self._budget_policies[profile.budget_policy_id]
        prompt = self._prompt_repository.get(profile.prompt_version_id)
        if prompt is None:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="failed",
                error=RuntimeErrorDetail(
                    code="prompt_not_found",
                    message="Prompt version was not found",
                ),
            )
        try:
            rendered_prompt = render_prompt(prompt, {})
        except PromptRenderError:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="failed",
                error=RuntimeErrorDetail(
                    code="prompt_render_failed",
                    message="Prompt version could not be rendered",
                ),
            )

        request = LLMRequest(
            model=self._model,
            messages=[
                LLMMessage(
                    role="system",
                    content=rendered_prompt,
                ),
                LLMMessage(
                    role="user",
                    content=message,
                ),
            ],
            response_schema=RouteDecision.model_json_schema(),
        )
        try:
            response = self._provider.generate(request)
            decision = parse_route_decision(response)
        except LLMInvalidOutputError:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="failed",
                error=RuntimeErrorDetail(
                    code="invalid_model_output",
                    message="Model output failed validation",
                ),
            )
        except LLMProviderUnavailableError:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="failed",
                error=RuntimeErrorDetail(
                    code="provider_unavailable",
                    message="LLM provider is unavailable",
                ),
            )
        except LLMProviderError:
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="failed",
                error=RuntimeErrorDetail(
                    code="provider_error",
                    message="LLM provider request failed",
                ),
            )

        if decision.route == "direct":
            if decision.output_text is None:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="failed",
                    route="direct",
                    error=RuntimeErrorDetail(
                        code="invalid_model_output",
                        message="Model output did not include direct response text",
                    ),
                )
            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="succeeded",
                route="direct",
                output_text=decision.output_text,
            )
        if decision.route == "retrieve":
            if not profile.knowledge_base_ids:
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
            if budget_policy.max_steps < 2:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="rejected",
                    route="retrieve",
                    error=RuntimeErrorDetail(
                        code="budget_exceeded",
                        message="Runtime step budget is exhausted",
                    ),
                )

            retrieved_text = self._retriever.retrieve(
                knowledge_base_ids=profile.knowledge_base_ids,
                query=message,
            )

            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="succeeded",
                route="retrieve",
                output_text=retrieved_text,
            )

        if decision.route == "clarify":
            if decision.output_text is None:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="failed",
                    route="clarify",
                    error=RuntimeErrorDetail(
                        code="invalid_model_output",
                        message="Model output did not include clarification text",
                    ),
                )

            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status="succeeded",
                route="clarify",
                output_text=decision.output_text,
            )

        if decision.route == "tool":
            if decision.tool_name is None or decision.args is None:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="failed",
                    route="tool",
                    error=RuntimeErrorDetail(
                        code="invalid_model_output",
                        message="Model output did not include a complete tool call",
                    ),
                )

            if budget_policy.max_steps < 2:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="rejected",
                    route="tool",
                    error=RuntimeErrorDetail(
                        code="budget_exceeded",
                        message="Runtime step budget is exhausted",
                    ),
                )
            if budget_policy.max_tool_calls < 1:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="rejected",
                    route="tool",
                    error=RuntimeErrorDetail(
                        code="budget_exceeded",
                        message="Runtime tool-call budget is exhausted",
                    ),
                )

            tool_call = ToolCall(
                call_id=generate_call_id(),
                tool_name=decision.tool_name,
                arguments=decision.args,
                profile_id=profile.profile_id,
                thread_id=thread_id,
            )

            tool_result = self._tool_registry.execute(
                call=tool_call,
                profile=profile,
                actor_role=self._actor_role,
                approval_granted=False,
                budget_policy=BudgetPolicy(
                    budget_policy_id=budget_policy.budget_policy_id,
                    max_calls=budget_policy.max_tool_calls,
                ),
                calls_used=0,
            )

            if tool_result.status == "succeeded":
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="succeeded",
                    route="tool",
                    tool_result=tool_result,
                )

            if tool_result.error is None:
                return RuntimeResult(
                    profile_id=profile_id,
                    thread_id=thread_id,
                    status="failed",
                    route="tool",
                    tool_result=tool_result,
                    error=RuntimeErrorDetail(
                        code="invalid_tool_result",
                        message="Tool registry returned an invalid result",
                    ),
                )

            return RuntimeResult(
                profile_id=profile_id,
                thread_id=thread_id,
                status=tool_result.status,
                route="tool",
                tool_result=tool_result,
                error=RuntimeErrorDetail(
                    code=tool_result.error.code,
                    message=tool_result.error.message,
                ),
            )

        return RuntimeResult(
            profile_id=profile_id,
            thread_id=thread_id,
            status="failed",
            error=RuntimeErrorDetail(
                code="invalid_model_output",
                message="Model output contained an unsupported route",
            ),
        )
