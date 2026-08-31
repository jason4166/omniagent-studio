from datetime import UTC, datetime

from omniagent.llm import LLMProvider
from omniagent.profiles import AgentProfile
from omniagent.prompts import InMemoryPromptVersionRepository, PromptVersionService
from omniagent.repositories import InMemoryAgentProfileRepository
from omniagent.retrieval import Retriever
from omniagent.runtime import AgentRuntime, RuntimeBudgetPolicy
from omniagent.tool_catalog import build_default_tool_registry

DEFAULT_RUNTIME_MODEL = "fake-runtime-model"


def build_default_agent_runtime(
    provider: LLMProvider,
    retriever: Retriever,
    *,
    actor_role: str = "sales_member",
    model: str = DEFAULT_RUNTIME_MODEL,
) -> AgentRuntime:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            knowledge_base_ids=["general-kb-v1"],
            prompt_version_id="general-kb:v1",
            budget_policy_id="runtime-standard",
            approval_policy_id="safe-default",
        )
    )
    profile_repository.save(
        AgentProfile(
            profile_id="product-support",
            tool_ids=["lookup_product", "check_warranty"],
            prompt_version_id="product-support:v1",
            budget_policy_id="runtime-standard",
            approval_policy_id="safe-default",
        )
    )
    profile_repository.save(
        AgentProfile(
            profile_id="warranty-support",
            tool_ids=["check_warranty"],
            prompt_version_id="product-support:v1",
            budget_policy_id="runtime-standard",
            approval_policy_id="safe-default",
        )
    )

    prompt_repository = InMemoryPromptVersionRepository()
    prompt_service = PromptVersionService(prompt_repository)
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    prompt_service.create(
        prompt_version_id="general-kb:v1",
        content=(
            "Route general knowledge requests using direct, retrieve, or clarify. "
            "Do not propose named business tools."
        ),
        created_at=created_at,
    )
    prompt_service.create(
        prompt_version_id="product-support:v1",
        content=(
            "Route product support requests using direct, lookup_product, "
            "check_warranty, or clarify."
        ),
        created_at=created_at,
    )

    budget_policies = {
        "runtime-standard": RuntimeBudgetPolicy(
            budget_policy_id="runtime-standard",
            max_model_calls=1,
            max_tool_calls=1,
            max_steps=2,
        )
    }

    return AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role=actor_role,
        tool_registry=build_default_tool_registry(),
        retriever=retriever,
        budget_policies=budget_policies,
        knowledge_base_ids={"general-kb-v1"},
        model=model,
    )
