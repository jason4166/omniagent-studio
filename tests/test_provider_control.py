import httpx
import pytest
from openai import OpenAI

from omniagent.llm import (
    FakeLLM,
    LLMAuthenticationError,
    LLMInvalidOutputError,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnknownModelError,
    LLMUsage,
)
from omniagent.openai_adapters import OpenAICompatibleChatProvider, OpenAILLMProvider
from omniagent.providers import ControlledProvider, ProviderBinding, model_attempt, model_usage
from omniagent.telemetry import Telemetry

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


@pytest.mark.parametrize("content", [" " * 22, "\r\n\t", "\u00a0\u2003"])
@pytest.mark.parametrize("schema", [None, {"type": "object"}])
def test_compatible_whitespace_records_usage_and_failed_span_without_retry_or_fallback(
    content, schema
):
    requests = []

    def complete(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-usage-regression",
                "object": "chat.completion",
                "created": 0,
                "model": "compatible-returned",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 31, "completion_tokens": 22, "total_tokens": 53},
            },
        )

    secondary = FakeLLM(LLMResponse(model="secondary-model", content="{}"))
    recorded, attempts = [], []
    telemetry = Telemetry()
    usage_token = model_usage.set(recorded.append)
    attempt_token = model_attempt.set(lambda: attempts.append(1))
    try:
        with OpenAI(
            api_key="synthetic-test-value",
            base_url="https://provider.invalid/v1",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(complete)),
        ) as client:
            provider = ControlledProvider(
                [
                    ProviderBinding("primary", OpenAICompatibleChatProvider(client)),
                    ProviderBinding("secondary", secondary),
                ]
            )
            with telemetry.activate(), pytest.raises(LLMInvalidOutputError, match="whitespace"):
                provider.generate(
                    LLMRequest(
                        model="compatible-requested",
                        messages=[
                            LLMMessage(role="user", content="Describe the available actions.")
                        ],
                        response_schema=schema,
                    )
                )
    finally:
        model_attempt.reset(attempt_token)
        model_usage.reset(usage_token)
        telemetry.shutdown()

    assert len(requests) == 1
    assert attempts == [1]
    assert secondary.requests == []
    assert recorded == [LLMUsage(input_tokens=31, output_tokens=22, total_tokens=53)]
    spans = [record for record in telemetry.local.snapshot() if record["name"] == "llm"]
    assert len(spans) == 1
    assert spans[0]["status"] == "error"
    assert spans[0]["attributes"]["input_tokens"] == 31
    assert spans[0]["attributes"]["output_tokens"] == 22
    assert spans[0]["attributes"]["total_tokens"] == 53
    assert spans[0]["attributes"]["requested_model_id"] == "compatible-requested"
    assert spans[0]["attributes"]["model_id"] == "compatible-returned"


@pytest.mark.parametrize(
    ("status", "output", "rejected"),
    [
        ("completed", "", True),
        ("incomplete", '{"answer":"WITHHELD_OUTPUT_SENTINEL"}', True),
        ("completed", '{"answer":"ok"}', False),
    ],
)
def test_responses_account_known_usage_exactly_once_even_when_rejected(status, output, rejected):
    requests = []

    def complete(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp-usage-regression",
                "object": "response",
                "created_at": 0,
                "status": status,
                "model": "responses-returned",
                "output": [
                    {
                        "id": "reasoning-private",
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "PRIVATE_REASONING_SENTINEL"}],
                    },
                    {
                        "id": "message-test",
                        "type": "message",
                        "role": "assistant",
                        "status": status,
                        "content": [{"type": "output_text", "text": output, "annotations": []}],
                    },
                ],
                "usage": {"input_tokens": 31, "output_tokens": 22, "total_tokens": 53},
            },
        )

    secondary = FakeLLM(LLMResponse(model="secondary-model", content="{}"))
    recorded, attempts = [], []
    telemetry = Telemetry()
    usage_token = model_usage.set(recorded.append)
    attempt_token = model_attempt.set(lambda: attempts.append(1))
    try:
        with OpenAI(
            api_key="synthetic-test-value",
            base_url="https://provider.invalid/v1",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(complete)),
        ) as client:
            provider = ControlledProvider(
                [
                    ProviderBinding("primary", OpenAILLMProvider(client)),
                    ProviderBinding("secondary", secondary),
                ]
            )
            request = LLMRequest(
                model="responses-requested",
                messages=[LLMMessage(role="user", content="Describe the available actions.")],
                response_schema={"type": "object"},
            )
            with telemetry.activate():
                if rejected:
                    with pytest.raises(LLMInvalidOutputError, match="no complete text") as caught:
                        provider.generate(request)
                    public_error = str(caught.value) + repr(vars(caught.value))
                    assert "WITHHELD_OUTPUT_SENTINEL" not in public_error
                    assert "PRIVATE_REASONING_SENTINEL" not in public_error
                else:
                    result = provider.generate(request)
                    assert result.content == output
                    assert "PRIVATE_REASONING_SENTINEL" not in result.model_dump_json()
    finally:
        model_attempt.reset(attempt_token)
        model_usage.reset(usage_token)
        telemetry.shutdown()

    assert len(requests) == 1
    assert attempts == [1]
    assert secondary.requests == []
    assert recorded == [LLMUsage(input_tokens=31, output_tokens=22, total_tokens=53)]
    spans = [record for record in telemetry.local.snapshot() if record["name"] == "llm"]
    assert len(spans) == 1
    assert spans[0]["status"] == ("error" if rejected else "unset")
    assert spans[0]["attributes"]["input_tokens"] == 31
    assert spans[0]["attributes"]["output_tokens"] == 22
    assert spans[0]["attributes"]["total_tokens"] == 53
    assert spans[0]["attributes"]["requested_model_id"] == "responses-requested"
    assert spans[0]["attributes"]["model_id"] == "responses-returned"
    assert "WITHHELD_OUTPUT_SENTINEL" not in repr(spans)
    assert "PRIVATE_REASONING_SENTINEL" not in repr(spans)
