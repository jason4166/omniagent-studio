import pytest

from omniagent.llm import (
    FakeLLM,
    LLMAuthenticationError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnknownModelError,
)
from omniagent.providers import ControlledProvider, ProviderBinding, model_attempt

pytestmark = pytest.mark.unit


def test_explicit_provider_fallback_reserves_every_attempt_and_reports_degradation():
    primary = FakeLLM(LLMResponse(model="one", content="{}"), LLMTimeoutError())
    secondary = FakeLLM(LLMResponse(model="two", content='{"answer":"ok"}'))
    control = ControlledProvider(
        [ProviderBinding("primary", primary), ProviderBinding("secondary", secondary, "two")]
    )
    reservations = []
    token = model_attempt.set(lambda: reservations.append(1))
    try:
        result = control.generate(
            LLMRequest(model="one", messages=[], response_schema={"type": "object"})
        )
    finally:
        model_attempt.reset(token)
    assert result.model == "two" and len(reservations) == 3
    assert control.last["degraded"] is True
    assert control.last["provider_id"] == "secondary"


@pytest.mark.parametrize("failure", [LLMAuthenticationError(), LLMUnknownModelError()])
def test_provider_auth_and_missing_model_do_not_fallback(failure):
    primary = FakeLLM(LLMResponse(model="one", content="{}"), failure)
    secondary = FakeLLM(LLMResponse(model="two", content="{}"))
    control = ControlledProvider(
        [ProviderBinding("primary", primary), ProviderBinding("secondary", secondary, "two")]
    )
    with pytest.raises(type(failure)):
        control.generate(LLMRequest(model="one", messages=[]))
    assert len(primary.requests) == 1 and secondary.requests == []


def test_real_provider_can_never_silently_fallback_to_fake():
    with pytest.raises(ValueError, match="Fake"):
        ControlledProvider(
            [
                ProviderBinding("primary", FakeLLM(LLMResponse(model="x", content="{}"))),
                ProviderBinding("fake", FakeLLM(LLMResponse(model="x", content="{}"))),
            ]
        )


def test_invalid_schema_response_still_accounts_received_usage():
    from omniagent.llm import LLMInvalidOutputError, LLMUsage
    from omniagent.providers import model_usage

    usage = LLMUsage(input_tokens=5, output_tokens=2, total_tokens=7)
    provider = ControlledProvider(
        [ProviderBinding("fake", FakeLLM(LLMResponse(model="x", content="invalid", usage=usage)))]
    )
    recorded = []
    token = model_usage.set(recorded.append)
    try:
        with pytest.raises(LLMInvalidOutputError):
            provider.generate(
                LLMRequest(model="x", messages=[], response_schema={"type": "object"})
            )
    finally:
        model_usage.reset(token)
    assert recorded == [usage]
