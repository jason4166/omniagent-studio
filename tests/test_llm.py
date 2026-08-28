import pytest
from pydantic import ValidationError

from omniagent.llm import (
    FakeLLM,
    LLMInvalidOutputError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnknownModelError,
    RouteDecision,
    parse_route_decision,
)


def test_fake_llm_returns_configured_response_through_provider_contract() -> None:
    expected = LLMResponse(model="local-fake", content="billing")
    provider: LLMProvider = FakeLLM(response=expected)
    request = LLMRequest(
        model="local-fake",
        messages=[LLMMessage(role="user", content="Refund order")],
    )

    actual = provider.generate(request)

    assert actual == expected


def test_fake_llm_records_requests_in_call_order() -> None:
    response = LLMResponse(model="local-fake", content="billing")
    fllm = FakeLLM(response)
    request1 = LLMRequest(
        model="local-fake",
        messages=[LLMMessage(role="user", content="Refund order")],
    )
    request2 = LLMRequest(
        model="local-fake",
        messages=[LLMMessage(role="user", content="hello world")],
    )

    fllm.generate(request1)
    fllm.generate(request2)

    assert fllm.requests == [request1, request2]


def test_fake_llm_raises_timeout_and_records_request() -> None:
    response = LLMResponse(model="local-fake", content="billing")
    fllm = FakeLLM(response, LLMTimeoutError())
    request = LLMRequest(
        model="local-fake",
        messages=[LLMMessage(role="user", content="Refund order")],
    )
    with pytest.raises(LLMTimeoutError):
        fllm.generate(request)
    assert fllm.requests == [request]


def test_fake_llm_rejects_unknown_model_and_records_request() -> None:
    response = LLMResponse(model="local-fake", content="billing")
    fllm = FakeLLM(response)
    request = LLMRequest(
        model="missing-model",
        messages=[LLMMessage(role="user", content="Refund order")],
    )
    with pytest.raises(LLMUnknownModelError):
        fllm.generate(request)
    assert fllm.requests == [request]


def test_fake_llm_invalid_output_is_rejected() -> None:
    response = LLMResponse(model="local-fake", content="not-json")
    fllm = FakeLLM(response)
    request = LLMRequest(
        model="local-fake",
        messages=[LLMMessage(role="user", content="Refund order")],
    )
    x1 = fllm.generate(request)
    with pytest.raises(LLMInvalidOutputError):
        parse_route_decision(x1)
    assert fllm.requests == [request]


def test_route_decision_accepts_direct_without_tool_fields() -> None:
    decision = RouteDecision(
        route="direct",
        reason="The request can be answered directly.",
        confidence=0.9,
    )

    assert decision.route == "direct"
    assert decision.tool_name is None
    assert decision.args is None


def test_route_decision_accepts_tool_with_name_and_args() -> None:
    decision = RouteDecision(
        route="tool",
        reason="Order status requires a tool call.",
        confidence=0.8,
        tool_name="get_order",
        args={"order_id": "A123"},
    )

    assert decision.tool_name == "get_order"
    assert decision.args == {"order_id": "A123"}


def test_route_decision_rejects_tool_without_required_fields() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            route="tool",
            reason="A tool is required but not specified.",
            confidence=0.8,
        )


def test_route_decision_rejects_non_tool_with_tool_fields() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            route="direct",
            reason="Direct routes cannot carry tool fields.",
            confidence=0.9,
            tool_name="get_order",
            args={"order_id": "A123"},
        )


def test_route_decision_accepts_retrieve_without_tool_fields() -> None:
    decision = RouteDecision(
        route="retrieve",
        reason="Knowledge retrieval is required.",
        confidence=0.75,
    )

    assert decision.route == "retrieve"
    assert decision.tool_name is None
    assert decision.args is None


def test_route_decision_accepts_clarify_without_tool_fields() -> None:
    decision = RouteDecision(
        route="clarify",
        reason="More information is required.",
        confidence=0.6,
    )

    assert decision.route == "clarify"
    assert decision.tool_name is None
    assert decision.args is None


def test_route_decision_rejects_confidence_above_one() -> None:
    with pytest.raises(ValidationError):
        RouteDecision(
            route="direct",
            reason="Confidence is outside the allowed range.",
            confidence=1.1,
        )


def test_route_decision_rejects_unknown_route_from_external_data() -> None:
    with pytest.raises(ValidationError):
        RouteDecision.model_validate(
            {
                "route": "billing",
                "reason": "The route is not part of the contract.",
                "confidence": 0.8,
            }
        )


def test_fake_llm_raises_rate_limit_and_records_request() -> None:
    response = LLMResponse(model="local-fake", content="billing")
    fllm = FakeLLM(response, LLMRateLimitError())
    request = LLMRequest(
        model="local-fake",
        messages=[LLMMessage(role="user", content="Refund order")],
    )
    with pytest.raises(LLMRateLimitError):
        fllm.generate(request)
    assert fllm.requests == [request]
