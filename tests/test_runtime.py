from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from omniagent.llm import (
    FakeLLM,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMResponse,
    LLMTimeoutError,
)
from omniagent.profiles import AgentProfile
from omniagent.prompts import InMemoryPromptVersionRepository, PromptVersionService
from omniagent.repositories import InMemoryAgentProfileRepository
from omniagent.retrieval import FakeRetriever
from omniagent.runtime import (
    AgentRuntime,
    RuntimeBudgetPolicy,
    RuntimeConfigurationError,
    RuntimeErrorDetail,
    RuntimeResult,
    validate_runtime_configuration,
)
from omniagent.tool_catalog import build_default_tool_registry
from omniagent.tool_registry import ToolRegistry
from omniagent.tooling import ToolResult


def test_runtime_result_rejects_success_with_error() -> None:
    with pytest.raises(
        ValidationError,
        match="succeeded result must not contain error",
    ):
        RuntimeResult(
            profile_id="general-kb",
            thread_id="thread-001",
            status="succeeded",
            route="direct",
            output_text="Synthetic direct response",
            error=RuntimeErrorDetail(
                code="invalid_model_output",
                message="Model output failed validation",
            ),
        )


def test_runtime_result_rejects_tool_result_for_non_tool_route() -> None:
    tool_result = ToolResult(
        call_id="call-lookup-001",
        status="succeeded",
        data={"sku": "DEMO-100"},
        error=None,
        duration_ms=0.1,
    )

    with pytest.raises(ValidationError, match="tool_result requires tool route"):
        RuntimeResult(
            profile_id="product-support",
            thread_id="thread-001",
            status="succeeded",
            route="direct",
            output_text="Synthetic direct response",
            tool_result=tool_result,
        )


def test_runtime_result_allows_tool_route_stopped_before_execution() -> None:
    result = RuntimeResult(
        profile_id="product-support",
        thread_id="thread-001",
        status="rejected",
        route="tool",
        error=RuntimeErrorDetail(
            code="budget_exceeded",
            message="Runtime budget is exhausted",
        ),
    )

    assert result.tool_result is None


def test_runtime_budget_policy_rejects_more_than_one_tool_call() -> None:
    with pytest.raises(
        ValidationError,
    ):
        RuntimeBudgetPolicy(
            budget_policy_id="invalid-budget",
            max_model_calls=1,
            max_tool_calls=2,
            max_steps=2,
        )


def test_runtime_rejects_missing_profile_before_provider_call() -> None:
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content='{"route":"direct","reason":"synthetic","confidence":1.0}',
        )
    )
    retriever = FakeRetriever(response="Synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=InMemoryAgentProfileRepository(),
        prompt_repository=InMemoryPromptVersionRepository(),
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={},
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="missing-profile",
        thread_id="thread-001",
        message="Synthetic request",
    )

    assert result.profile_id == "missing-profile"
    assert result.thread_id == "thread-001"
    assert result.status == "rejected"
    assert result.route is None
    assert result.error is not None
    assert result.error.code == "profile_not_found"
    assert provider.requests == []
    assert retriever.requests == []


def test_runtime_rejects_disabled_profile_before_provider_call() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="disabled-profile",
            enabled=False,
            prompt_version_id="disabled:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "disabled:v1",
        "Disabled profile prompt",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content='{"route":"direct","reason":"synthetic","confidence":1.0}',
        )
    )
    retriever = FakeRetriever(response="Synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=1,
            )
        },
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="disabled-profile",
        thread_id="thread-002",
        message="Synthetic request",
    )

    assert result.profile_id == "disabled-profile"
    assert result.thread_id == "thread-002"
    assert result.status == "rejected"
    assert result.route is None
    assert result.error is not None
    assert result.error.code == "profile_disabled"
    assert provider.requests == []
    assert retriever.requests == []


def test_runtime_direct_route_uses_prompt_and_returns_output() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "general:v1",
        "Route synthetic requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=(
                '{"route":"direct","reason":"No external capability is required",'
                '"confidence":1.0,"output_text":"Synthetic direct answer"}'
            ),
        )
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=1,
            )
        },
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="general-kb",
        thread_id="thread-direct-001",
        message="Give me a synthetic direct answer",
    )

    assert result.profile_id == "general-kb"
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.model == "fake-model"
    assert [(item.role, item.content) for item in request.messages] == [
        ("system", "Route synthetic requests safely."),
        ("user", "Give me a synthetic direct answer"),
    ]
    assert retriever.requests == []
    assert result.status == "succeeded"
    assert result.route == "direct"
    assert result.output_text == "Synthetic direct answer"
    assert result.error is None


def test_runtime_rejects_direct_route_without_output_text() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "general:v1",
        "Route synthetic requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=(
                '{"route":"direct","reason":"No external capability is required","confidence":1.0}'
            ),
        )
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=1,
            )
        },
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="general-kb",
        thread_id="thread-direct-invalid-001",
        message="Give me a synthetic direct answer",
    )

    assert result.status == "failed"
    assert result.route == "direct"
    assert result.output_text is None
    assert result.error is not None
    assert result.error.code == "invalid_model_output"
    assert len(provider.requests) == 1
    assert retriever.requests == []


def test_runtime_retrieve_route_uses_profile_knowledge_bases() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            knowledge_base_ids=["general-kb-v1"],
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "general:v1",
        "Route synthetic requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=(
                '{"route":"retrieve","reason":"Synthetic knowledge is required","confidence":1.0}'
            ),
        )
    )
    retriever = FakeRetriever(response="Synthetic support is available from 09:00 to 18:00.")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=2,
            )
        },
        knowledge_base_ids={"general-kb-v1"},
        model="fake-model",
    )

    result = runtime.run(
        profile_id="general-kb",
        thread_id="thread-retrieve-001",
        message="What are the synthetic support hours?",
    )

    assert result.status == "succeeded"
    assert result.route == "retrieve"
    assert result.output_text == ("Synthetic support is available from 09:00 to 18:00.")
    assert result.error is None
    assert len(provider.requests) == 1
    assert retriever.requests == [
        (
            ("general-kb-v1",),
            "What are the synthetic support hours?",
        )
    ]


def test_runtime_rejects_retrieve_route_without_profile_knowledge_base() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="product-support",
            tool_ids=["lookup_product", "check_warranty"],
            prompt_version_id="support:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "support:v1",
        "Route synthetic product requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=(
                '{"route":"retrieve","reason":"Synthetic knowledge is required","confidence":1.0}'
            ),
        )
    )
    retriever = FakeRetriever(response="Must not be returned")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=build_default_tool_registry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=1,
                max_steps=2,
            )
        },
        knowledge_base_ids={"general-kb-v1"},
        model="fake-model",
    )

    result = runtime.run(
        profile_id="product-support",
        thread_id="thread-retrieve-rejected-001",
        message="Search synthetic internal knowledge",
    )

    assert result.status == "rejected"
    assert result.route == "retrieve"
    assert result.output_text is None
    assert result.error is not None
    assert result.error.code == "retrieval_not_allowed"
    assert len(provider.requests) == 1
    assert retriever.requests == []


@pytest.mark.parametrize(
    ("response_content", "expected_status", "expected_output", "expected_error_code"),
    [
        (
            (
                '{"route":"clarify","reason":"A synthetic serial number is required",'
                '"confidence":1.0,"output_text":"Please provide the synthetic serial number."}'
            ),
            "succeeded",
            "Please provide the synthetic serial number.",
            None,
        ),
        (
            (
                '{"route":"clarify","reason":"A synthetic serial number is required",'
                '"confidence":1.0}'
            ),
            "failed",
            None,
            "invalid_model_output",
        ),
    ],
)
def test_runtime_clarify_route_requires_output_text(
    response_content: str,
    expected_status: str,
    expected_output: str | None,
    expected_error_code: str | None,
) -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="product-support",
            prompt_version_id="support:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "support:v1",
        "Route synthetic product requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=response_content,
        )
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=1,
            )
        },
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="product-support",
        thread_id="thread-clarify-001",
        message="Check a synthetic warranty",
    )

    assert result.status == expected_status
    assert result.route == "clarify"
    assert result.output_text == expected_output
    if expected_error_code is None:
        assert result.error is None
    else:
        assert result.error is not None
        assert result.error.code == expected_error_code
    assert len(provider.requests) == 1
    assert retriever.requests == []


@pytest.mark.parametrize(
    (
        "profile_id",
        "tool_ids",
        "profile_knowledge_base_ids",
        "response_content",
        "max_steps",
        "max_tool_calls",
        "expected_message",
    ),
    [
        (
            "general-kb",
            [],
            ["general-kb-v1"],
            ('{"route":"retrieve","reason":"Synthetic knowledge is required","confidence":1.0}'),
            1,
            1,
            "Runtime step budget is exhausted",
        ),
        (
            "product-support",
            ["lookup_product"],
            [],
            (
                '{"route":"tool","reason":"Synthetic product data is required",'
                '"confidence":1.0,"tool_name":"lookup_product",'
                '"args":{"sku":"DEMO-100"}}'
            ),
            2,
            0,
            "Runtime tool-call budget is exhausted",
        ),
    ],
)
def test_runtime_stops_before_second_step_when_budget_is_exhausted(
    profile_id: str,
    tool_ids: list[str],
    profile_knowledge_base_ids: list[str],
    response_content: str,
    max_steps: int,
    max_tool_calls: int,
    expected_message: str,
) -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id=profile_id,
            tool_ids=tool_ids,
            knowledge_base_ids=profile_knowledge_base_ids,
            prompt_version_id="runtime:v1",
            budget_policy_id="bounded",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "runtime:v1",
        "Route synthetic requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=response_content,
        )
    )
    retriever = FakeRetriever(response="Must not be returned")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=build_default_tool_registry(),
        retriever=retriever,
        budget_policies={
            "bounded": RuntimeBudgetPolicy(
                budget_policy_id="bounded",
                max_model_calls=1,
                max_tool_calls=max_tool_calls,
                max_steps=max_steps,
            )
        },
        knowledge_base_ids={"general-kb-v1"},
        model="fake-model",
    )

    result = runtime.run(
        profile_id=profile_id,
        thread_id="thread-budget-001",
        message="Use a synthetic second-step capability",
    )

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "budget_exceeded"
    assert result.error.message == expected_message
    assert len(provider.requests) == 1
    assert retriever.requests == []


def test_same_runtime_enforces_profile_tool_allowlist() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            knowledge_base_ids=["general-kb-v1"],
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    profile_repository.save(
        AgentProfile(
            profile_id="product-support",
            tool_ids=["lookup_product", "check_warranty"],
            prompt_version_id="support:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    prompt_service = PromptVersionService(prompt_repository)
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    prompt_service.create("general:v1", "General routing prompt.", created_at)
    prompt_service.create("support:v1", "Product support routing prompt.", created_at)
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=(
                '{"route":"tool","reason":"Synthetic product data is required",'
                '"confidence":1.0,"tool_name":"lookup_product",'
                '"args":{"sku":"DEMO-100"}}'
            ),
        )
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=build_default_tool_registry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=1,
                max_steps=2,
            )
        },
        knowledge_base_ids={"general-kb-v1"},
        model="fake-model",
    )

    allowed_result = runtime.run(
        profile_id="product-support",
        thread_id="thread-tool-allowed-001",
        message="Look up synthetic product DEMO-100",
    )
    rejected_result = runtime.run(
        profile_id="general-kb",
        thread_id="thread-tool-rejected-001",
        message="Look up synthetic product DEMO-100",
    )

    assert allowed_result.status == "succeeded"
    assert allowed_result.route == "tool"
    assert allowed_result.error is None
    assert allowed_result.tool_result is not None
    assert allowed_result.tool_result.status == "succeeded"
    assert allowed_result.tool_result.data == {
        "sku": "DEMO-100",
        "name": "Synthetic Keyboard",
        "available": True,
    }
    assert rejected_result.status == "rejected"
    assert rejected_result.route == "tool"
    assert rejected_result.error is not None
    assert rejected_result.error.code == "tool_not_allowed"
    assert rejected_result.tool_result is not None
    assert rejected_result.tool_result.status == "rejected"
    assert allowed_result.tool_result.call_id != rejected_result.tool_result.call_id
    assert len(provider.requests) == 2
    assert retriever.requests == []


@pytest.mark.parametrize(
    ("response_content", "provider_error", "expected_code", "expected_message"),
    [
        (
            "not-json",
            None,
            "invalid_model_output",
            "Model output failed validation",
        ),
        (
            '{"route":"direct","reason":"synthetic","confidence":1.0}',
            LLMProviderUnavailableError("synthetic unavailable"),
            "provider_unavailable",
            "LLM provider is unavailable",
        ),
        (
            '{"route":"direct","reason":"synthetic","confidence":1.0}',
            LLMTimeoutError("synthetic timeout"),
            "provider_error",
            "LLM provider request failed",
        ),
    ],
)
def test_runtime_maps_model_and_provider_errors(
    response_content: str,
    provider_error: LLMProviderError | None,
    expected_code: str,
    expected_message: str,
) -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "general:v1",
        "Route synthetic requests safely.",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=response_content,
        ),
        error=provider_error,
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=1,
            )
        },
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="general-kb",
        thread_id="thread-model-error-001",
        message="Synthetic request",
    )

    assert result.status == "failed"
    assert result.route is None
    assert result.output_text is None
    assert result.error is not None
    assert result.error.code == expected_code
    assert result.error.message == expected_message
    assert len(provider.requests) == 1
    assert retriever.requests == []


def test_runtime_maps_prompt_render_error_before_provider_call() -> None:
    profile_repository = InMemoryAgentProfileRepository()
    profile_repository.save(
        AgentProfile(
            profile_id="general-kb",
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        )
    )
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "general:v1",
        "Route requests for {{agent_goal}}.",
        datetime(2026, 8, 31, tzinfo=UTC),
        variables=("agent_goal",),
    )
    provider = FakeLLM(
        response=LLMResponse(
            model="fake-model",
            content=(
                '{"route":"direct","reason":"synthetic","confidence":1.0,'
                '"output_text":"Must not be returned"}'
            ),
        )
    )
    retriever = FakeRetriever(response="Unused synthetic knowledge")
    runtime = AgentRuntime(
        profile_repository=profile_repository,
        prompt_repository=prompt_repository,
        provider=provider,
        actor_role="sales_member",
        tool_registry=ToolRegistry(),
        retriever=retriever,
        budget_policies={
            "standard": RuntimeBudgetPolicy(
                budget_policy_id="standard",
                max_model_calls=1,
                max_tool_calls=0,
                max_steps=1,
            )
        },
        knowledge_base_ids=set(),
        model="fake-model",
    )

    result = runtime.run(
        profile_id="general-kb",
        thread_id="thread-prompt-error-001",
        message="Synthetic request",
    )

    assert result.status == "failed"
    assert result.route is None
    assert result.error is not None
    assert result.error.code == "prompt_render_failed"
    assert provider.requests == []
    assert retriever.requests == []


def test_valid_runtime_configuration_passes() -> None:
    prompt_repository = InMemoryPromptVersionRepository()
    prompt_service = PromptVersionService(prompt_repository)
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    prompt_service.create("general:v1", "General prompt", created_at)
    prompt_service.create("support:v1", "Support prompt", created_at)
    profiles = [
        AgentProfile(
            profile_id="general-kb",
            knowledge_base_ids=["general-kb-v1"],
            prompt_version_id="general:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        ),
        AgentProfile(
            profile_id="product-support",
            tool_ids=["lookup_product", "check_warranty"],
            prompt_version_id="support:v1",
            budget_policy_id="standard",
            approval_policy_id="safe-default",
        ),
    ]
    budget_policies = {
        "standard": RuntimeBudgetPolicy(
            budget_policy_id="standard",
            max_model_calls=2,
            max_tool_calls=1,
            max_steps=3,
        )
    }

    validate_runtime_configuration(
        profiles=profiles,
        prompt_repository=prompt_repository,
        tool_registry=build_default_tool_registry(),
        budget_policies=budget_policies,
        knowledge_base_ids={"general-kb-v1"},
    )


@pytest.mark.parametrize(
    (
        "prompt_version_id",
        "budget_policy_id",
        "tool_ids",
        "profile_knowledge_base_ids",
        "known_knowledge_base_ids",
        "error_message",
    ),
    [
        (
            "missing:v1",
            "standard",
            ["lookup_product"],
            ["general-kb-v1"],
            {"general-kb-v1"},
            "references unknown prompt version 'missing:v1'",
        ),
        (
            "support:v1",
            "missing-budget",
            ["lookup_product"],
            ["general-kb-v1"],
            {"general-kb-v1"},
            "references unknown budget policy 'missing-budget'",
        ),
        (
            "support:v1",
            "standard",
            ["missing_tool"],
            ["general-kb-v1"],
            {"general-kb-v1"},
            "references unregistered tool 'missing_tool'",
        ),
        (
            "support:v1",
            "standard",
            ["lookup_product"],
            ["missing-kb"],
            {"general-kb-v1"},
            "references unknown knowledge base 'missing-kb'",
        ),
    ],
)
def test_runtime_configuration_rejects_unknown_reference(
    prompt_version_id: str,
    budget_policy_id: str,
    tool_ids: list[str],
    profile_knowledge_base_ids: list[str],
    known_knowledge_base_ids: set[str],
    error_message: str,
) -> None:
    prompt_repository = InMemoryPromptVersionRepository()
    PromptVersionService(prompt_repository).create(
        "support:v1",
        "Support prompt",
        datetime(2026, 8, 31, tzinfo=UTC),
    )
    profile = AgentProfile(
        profile_id="product-support",
        tool_ids=tool_ids,
        knowledge_base_ids=profile_knowledge_base_ids,
        prompt_version_id=prompt_version_id,
        budget_policy_id=budget_policy_id,
        approval_policy_id="safe-default",
    )
    budget_policies = {
        "standard": RuntimeBudgetPolicy(
            budget_policy_id="standard",
            max_model_calls=2,
            max_tool_calls=1,
            max_steps=3,
        )
    }

    with pytest.raises(RuntimeConfigurationError, match=error_message):
        validate_runtime_configuration(
            profiles=[profile],
            prompt_repository=prompt_repository,
            tool_registry=build_default_tool_registry(),
            budget_policies=budget_policies,
            knowledge_base_ids=known_knowledge_base_ids,
        )
