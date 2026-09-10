from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from openai import APITimeoutError, OpenAI

from omniagent.embeddings import EMBEDDING_DIMENSION, EmbeddingProviderError, embed_checked
from omniagent.llm import (
    LLMInvalidOutputError,
    LLMMessage,
    LLMRequest,
    LLMTimeoutError,
)
from omniagent.openai_adapters import (
    OpenAICompatibleChatProvider,
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
)


class StubResource:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("stub response was not configured")
        return self.response


class StubOpenAIClient:
    def __init__(
        self,
        *,
        responses: StubResource,
        embeddings: StubResource,
        chat_completions: StubResource,
    ) -> None:
        self.responses = responses
        self.embeddings = embeddings
        self.chat = SimpleNamespace(completions=chat_completions)


def make_client(
    *,
    llm_response: object | None = None,
    llm_error: Exception | None = None,
    embedding_response: object | None = None,
    chat_response: object | None = None,
    chat_error: Exception | None = None,
) -> tuple[OpenAI, StubOpenAIClient]:
    stub = StubOpenAIClient(
        responses=StubResource(llm_response, llm_error),
        embeddings=StubResource(embedding_response),
        chat_completions=StubResource(chat_response, chat_error),
    )
    return cast(OpenAI, stub), stub


def test_openai_llm_maps_request_and_structured_output_without_network() -> None:
    response = SimpleNamespace(
        status="completed",
        output_text='{"route":"direct"}',
        model="gpt-test",
        usage=SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18),
    )
    client, stub = make_client(llm_response=response)
    provider = OpenAILLMProvider(client)

    actual = provider.generate(
        LLMRequest(
            model="gpt-test",
            messages=[
                LLMMessage(role="system", content="Follow policy"),
                LLMMessage(role="user", content="Hello"),
            ],
            temperature=0.2,
            max_tokens=128,
            timeout_seconds=4,
            response_schema={"type": "object"},
        )
    )

    call = stub.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["input"] == [
        {"role": "system", "content": "Follow policy"},
        {"role": "user", "content": "Hello"},
    ]
    assert call["text"] == {
        "format": {
            "type": "json_schema",
            "name": "omniagent_response",
            "schema": {"type": "object"},
            "strict": True,
        }
    }
    assert call["store"] is False
    assert call["timeout"] == 4
    assert actual.content == response.output_text
    assert actual.usage is not None
    assert actual.usage.total_tokens == 18


def test_openai_llm_omits_structured_output_when_schema_is_absent() -> None:
    response = SimpleNamespace(
        status="completed",
        output_text="plain text",
        model="gpt-test",
        usage=None,
    )
    client, stub = make_client(llm_response=response)

    OpenAILLMProvider(client).generate(
        LLMRequest(
            model="gpt-test",
            messages=[LLMMessage(role="user", content="Hello")],
        )
    )

    assert "text" not in stub.responses.calls[0]


def test_openai_llm_translates_timeout_without_leaking_provider_detail() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    client, _ = make_client(llm_error=APITimeoutError(request))

    with pytest.raises(LLMTimeoutError, match="timed out"):
        OpenAILLMProvider(client).generate(
            LLMRequest(
                model="gpt-test",
                messages=[LLMMessage(role="user", content="Hello")],
            )
        )


def test_compatible_chat_maps_schema_to_json_mode_and_usage() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"route":"direct"}'),
                finish_reason="stop",
            )
        ],
        model="compatible-test",
        usage=SimpleNamespace(prompt_tokens=13, completion_tokens=5, total_tokens=18),
    )
    client, stub = make_client(chat_response=response)
    schema = {"type": "object", "required": ["route"]}

    actual = OpenAICompatibleChatProvider(client).generate(
        LLMRequest(
            model="compatible-test",
            messages=[LLMMessage(role="user", content="Route this request")],
            response_schema=schema,
            max_tokens=96,
            timeout_seconds=7,
        )
    )

    call = stub.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["messages"][0]["role"] == "system"
    assert "valid JSON" in call["messages"][0]["content"]
    assert '"required":["route"]' in call["messages"][0]["content"]
    assert call["messages"][1] == {"role": "user", "content": "Route this request"}
    assert call["max_tokens"] == 96
    assert call["timeout"] == 7
    assert actual.content == '{"route":"direct"}'
    assert actual.usage is not None
    assert actual.usage.total_tokens == 18
    assert actual.finish_reason == "stop"


def test_compatible_chat_omits_json_mode_for_plain_text() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="plain text"),
                finish_reason="length",
            )
        ],
        model="compatible-test",
        usage=None,
    )
    client, stub = make_client(chat_response=response)

    actual = OpenAICompatibleChatProvider(client).generate(
        LLMRequest(
            model="compatible-test",
            messages=[LLMMessage(role="user", content="Hello")],
        )
    )

    assert "response_format" not in stub.chat.completions.calls[0]
    assert actual.finish_reason == "length"


def test_compatible_chat_rejects_empty_provider_output() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=""),
                finish_reason="stop",
            )
        ],
        model="compatible-test",
        usage=None,
    )
    client, _ = make_client(chat_response=response)

    with pytest.raises(LLMInvalidOutputError, match="no text"):
        OpenAICompatibleChatProvider(client).generate(
            LLMRequest(
                model="compatible-test",
                messages=[LLMMessage(role="user", content="Hello")],
            )
        )


def test_openai_embedding_requests_existing_database_dimension_and_preserves_order() -> None:
    response = SimpleNamespace(
        data=[
            SimpleNamespace(index=1, embedding=[0.2] * EMBEDDING_DIMENSION),
            SimpleNamespace(index=0, embedding=[0.1] * EMBEDDING_DIMENSION),
        ]
    )
    client, stub = make_client(embedding_response=response)
    provider = OpenAIEmbeddingProvider(client=client)

    vectors = embed_checked(provider, ["first", "second"])

    assert vectors == [
        [0.1] * EMBEDDING_DIMENSION,
        [0.2] * EMBEDDING_DIMENSION,
    ]
    assert stub.embeddings.calls == [
        {
            "model": "text-embedding-3-small",
            "input": ["first", "second"],
            "dimensions": EMBEDDING_DIMENSION,
            "encoding_format": "float",
            "timeout": 30.0,
        }
    ]


def test_openai_embedding_does_not_call_provider_for_empty_batch() -> None:
    client, stub = make_client()
    provider = OpenAIEmbeddingProvider(client=client)

    assert provider.embed([]) == []
    assert stub.embeddings.calls == []


def test_openai_embedding_wraps_provider_errors() -> None:
    client, stub = make_client()
    stub.embeddings.error = RuntimeError("sensitive upstream detail")
    provider = OpenAIEmbeddingProvider(client=client)

    with pytest.raises(EmbeddingProviderError, match="request failed") as caught:
        provider.embed(["text"])
    assert "sensitive upstream detail" not in str(caught.value)


def test_embedding_timeout_keeps_transient_classification_and_parent_deadline():
    from omniagent.reliability import dependency_timeout, transient

    client, stub = make_client()
    stub.embeddings.error = APITimeoutError(
        request=httpx.Request("POST", "https://example.invalid")
    )
    provider = OpenAIEmbeddingProvider(client=client, timeout_seconds=30)
    token = dependency_timeout.set(2.5)
    try:
        with pytest.raises(EmbeddingProviderError) as caught:
            provider.embed(["synthetic"])
    finally:
        dependency_timeout.reset(token)
    assert transient(caught.value)
    assert stub.embeddings.calls[0]["timeout"] == 2.5
