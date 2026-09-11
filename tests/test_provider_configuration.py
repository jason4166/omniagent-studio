"""Provider configuration contracts through the real SDK and an offline HTTP transport."""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from openai import OpenAI

from omniagent import providers
from omniagent.errors import ErrorCode, PlatformError
from omniagent.llm import LLMMessage, LLMRequest
from omniagent.profiles import AgentProfile

pytestmark = pytest.mark.contract


@dataclass
class TransportHarness:
    clients: list[OpenAI] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    resolved_prefixes: list[str] = field(default_factory=list)

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = json.loads(request.content)
        common = {"id": "unit-response", "model": payload["model"]}
        if request.url.path == "/v1/responses":
            return httpx.Response(
                200,
                json={
                    **common,
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "output": [
                        {
                            "id": "unit-message",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"answer":"ok"}',
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                },
            )
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                **common,
                "object": "chat.completion",
                "created": 0,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"answer":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[TransportHarness]:
    harness = TransportHarness()
    for name in tuple(os.environ):
        if name.startswith(("OMNIAGENT_PROVIDER_", "OMNIAGENT_FALLBACK_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OMNIAGENT_PROVIDER_BASE_URL", "https://primary.example.invalid/v1")
    monkeypatch.setenv("OMNIAGENT_FALLBACK_BASE_URL", "https://secondary.example.invalid/v1")
    monkeypatch.setenv("OMNIAGENT_FALLBACK_MODEL", "unit-secondary")

    def synthetic_secret(prefix: str) -> str:
        harness.resolved_prefixes.append(prefix)
        return "synthetic-unit-credential-" + prefix

    def make_client(**kwargs: Any) -> OpenAI:
        client = OpenAI(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(harness.respond)),
        )
        harness.clients.append(client)
        return client

    monkeypatch.setattr(providers, "resolve_secret", synthetic_secret)
    monkeypatch.setattr(providers, "OpenAI", make_client)
    try:
        yield harness
    finally:
        for client in harness.clients:
            client.close()


def profile(*, fallback: bool = False) -> AgentProfile:
    return AgentProfile(
        profile_id="configuration-test",
        provider_id="primary-with-fallback" if fallback else "primary",
        model="unit-primary",
        prompt_version_id="unit-prompt",
        budget_policy_id="unit-budget",
        approval_policy_id="unit-approval",
    )


def request(model: str) -> LLMRequest:
    return LLMRequest(
        model=model,
        messages=[LLMMessage(role="user", content="Synthetic request")],
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        max_tokens=96,
        timeout_seconds=7,
    )


@pytest.mark.parametrize(
    "settings,expected_path,expected_strict,expected_reasoning",
    [
        ({}, "/v1/chat/completions", None, None),
        ({"API": "responses"}, "/v1/responses", True, None),
        (
            {"API": "responses", "SCHEMA_STRICT": "false", "REASONING_EFFORT": "none"},
            "/v1/responses",
            False,
            {"effort": "none"},
        ),
    ],
)
def test_configured_protocol_maps_sdk_request_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
    transport: TransportHarness,
    settings: dict[str, str],
    expected_path: str,
    expected_strict: bool | None,
    expected_reasoning: dict[str, str] | None,
) -> None:
    for suffix, value in settings.items():
        monkeypatch.setenv("OMNIAGENT_PROVIDER_" + suffix, value)
    with providers.configured_provider(profile(), None, {}) as configured:
        binding = configured.bindings[0]
        assert binding.provider_id == "primary"
        assert binding.model == "unit-primary"
        result = binding.provider.generate(request(binding.model))
        assert result.content == '{"answer":"ok"}'
        assert not transport.clients[0].is_closed()
    assert transport.clients[0].is_closed()
    assert transport.resolved_prefixes == ["OMNIAGENT_PROVIDER"]
    assert len(transport.requests) == 1
    outgoing = transport.requests[0]
    assert outgoing.url.path == expected_path
    assert outgoing.extensions["timeout"]["read"] == 7
    payload = json.loads(outgoing.content)
    if expected_strict is None:
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 96
        assert "thinking" not in payload
        assert "text" not in payload
    else:
        assert payload["text"]["format"]["strict"] is expected_strict
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["store"] is False
        assert payload["max_output_tokens"] == 96
    if expected_reasoning is None:
        assert "reasoning" not in payload
    else:
        assert payload["reasoning"] == expected_reasoning


@pytest.mark.parametrize(
    "settings,fallback",
    [
        ({"API": "unknown"}, False),
        ({"SCHEMA_STRICT": "true"}, True),
        ({"REASONING_EFFORT": "none"}, True),
        ({"THINKING": "unknown"}, False),
        ({"API": "responses", "THINKING": "disabled"}, True),
        ({"API": "responses", "SCHEMA_STRICT": "yes"}, False),
        ({"API": "responses", "REASONING_EFFORT": "medium"}, True),
    ],
)
def test_invalid_protocol_settings_fail_validation_and_close_created_clients(
    monkeypatch: pytest.MonkeyPatch,
    transport: TransportHarness,
    settings: dict[str, str],
    fallback: bool,
) -> None:
    prefix = "OMNIAGENT_FALLBACK" if fallback else "OMNIAGENT_PROVIDER"
    for suffix, value in settings.items():
        monkeypatch.setenv(prefix + "_" + suffix, value)
    with (
        pytest.raises(PlatformError) as caught,
        providers.configured_provider(profile(fallback=fallback), None, {}),
    ):
        pytest.fail("Invalid configuration must not yield a provider")
    assert caught.value.code == ErrorCode.VALIDATION
    assert len(transport.clients) == (2 if fallback else 1)
    assert all(client.is_closed() for client in transport.clients)
    assert transport.requests == []


@pytest.mark.parametrize("primary_chat", [True, False])
def test_primary_and_fallback_settings_remain_independent(
    monkeypatch: pytest.MonkeyPatch,
    transport: TransportHarness,
    primary_chat: bool,
) -> None:
    if primary_chat:
        monkeypatch.setenv("OMNIAGENT_PROVIDER_API", "chat_completions")
        monkeypatch.setenv("OMNIAGENT_PROVIDER_THINKING", "disabled")
    else:
        monkeypatch.setenv("OMNIAGENT_PROVIDER_API", "responses")
        monkeypatch.setenv("OMNIAGENT_PROVIDER_SCHEMA_STRICT", "true")
        monkeypatch.setenv("OMNIAGENT_PROVIDER_REASONING_EFFORT", "high")
    monkeypatch.setenv("OMNIAGENT_FALLBACK_API", "responses")
    monkeypatch.setenv("OMNIAGENT_FALLBACK_SCHEMA_STRICT", "false")
    monkeypatch.setenv("OMNIAGENT_FALLBACK_REASONING_EFFORT", "low" if primary_chat else "max")

    with providers.configured_provider(profile(fallback=True), None, {}) as configured:
        assert [(b.provider_id, b.model) for b in configured.bindings] == [
            ("primary", "unit-primary"),
            ("secondary", "unit-secondary"),
        ]
        for binding in configured.bindings:
            assert binding.model is not None
            assert binding.provider.generate(request(binding.model)).content == '{"answer":"ok"}'
        assert all(not client.is_closed() for client in transport.clients)
    assert len(transport.clients) == 2
    assert all(client.is_closed() for client in transport.clients)
    assert transport.resolved_prefixes == ["OMNIAGENT_PROVIDER", "OMNIAGENT_FALLBACK"]
    assert [r.url.host for r in transport.requests] == [
        "primary.example.invalid",
        "secondary.example.invalid",
    ]
    primary, secondary = [json.loads(r.content) for r in transport.requests]
    assert [primary["model"], secondary["model"]] == ["unit-primary", "unit-secondary"]
    if primary_chat:
        assert primary["thinking"] == {"type": "disabled"}
        assert "reasoning" not in primary
        assert "text" not in primary
    else:
        assert primary["reasoning"] == {"effort": "high"}
        assert primary["text"]["format"]["strict"] is True
        assert "thinking" not in primary
    assert secondary["reasoning"] == {"effort": "low" if primary_chat else "max"}
    assert secondary["text"]["format"]["strict"] is False
    assert "thinking" not in secondary
