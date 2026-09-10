import json
from collections.abc import Sequence
from time import perf_counter
from typing import Any, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from openai.types.responses import ResponseInputParam, ResponseTextConfigParam
from openai.types.responses.easy_input_message_param import EasyInputMessageParam

from omniagent.embeddings import EMBEDDING_DIMENSION, EmbeddingProviderError
from omniagent.llm import (
    LLMAuthenticationError,
    LLMInvalidOutputError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnknownModelError,
    LLMUsage,
)
from omniagent.reliability import RetryPolicy, dependency_timeout, retry_call
from omniagent.telemetry import span

_SUPPORTED_ROLES = {"user", "assistant", "system", "developer"}


class OpenAILLMProvider:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def generate(self, request: LLMRequest) -> LLMResponse:
        input_items = self._build_input(request)
        started_at = perf_counter()

        try:
            if request.response_schema is None:
                response = self._client.responses.create(
                    model=request.model,
                    input=input_items,
                    temperature=request.temperature,
                    max_output_tokens=request.max_tokens,
                    store=False,
                    timeout=request.timeout_seconds,
                )
            else:
                text_config: ResponseTextConfigParam = {
                    "format": {
                        "type": "json_schema",
                        "name": "omniagent_response",
                        "schema": request.response_schema,
                        "strict": True,
                    }
                }
                response = self._client.responses.create(
                    model=request.model,
                    input=input_items,
                    temperature=request.temperature,
                    max_output_tokens=request.max_tokens,
                    text=text_config,
                    store=False,
                    timeout=request.timeout_seconds,
                )
        except Exception as exc:
            raise _translate_llm_error(exc) from exc

        if response.status != "completed" or not response.output_text:
            raise LLMInvalidOutputError("OpenAI returned no complete text response")

        usage = None
        if response.usage is not None:
            usage = LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return LLMResponse(
            model=response.model,
            content=response.output_text,
            usage=usage,
            latency_ms=(perf_counter() - started_at) * 1000,
            finish_reason="stop",
        )

    @staticmethod
    def _build_input(request: LLMRequest) -> ResponseInputParam:
        input_items: ResponseInputParam = []
        for message in request.messages:
            if message.role not in _SUPPORTED_ROLES:
                raise LLMProviderError(f"unsupported OpenAI message role: {message.role}")
            input_items.append(
                cast(
                    EasyInputMessageParam,
                    {"role": message.role, "content": message.content},
                )
            )
        return input_items


class OpenAICompatibleChatProvider:
    def __init__(self, client: OpenAI, *, thinking: str | None = None) -> None:
        self._client = client
        if thinking not in {None, "enabled", "disabled"}:
            raise ValueError("Thinking extension must be explicitly enabled or disabled")
        self._thinking = thinking

    def generate(self, request: LLMRequest) -> LLMResponse:
        messages = self._build_messages(request)
        arguments: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "timeout": request.timeout_seconds,
        }
        if request.response_schema is not None:
            arguments["response_format"] = {"type": "json_object"}
        if self._thinking is not None:
            arguments["extra_body"] = {"thinking": {"type": self._thinking}}

        started_at = perf_counter()
        try:
            response = self._client.chat.completions.create(**arguments)
        except Exception as exc:
            raise _translate_llm_error(exc) from exc

        if not response.choices:
            raise LLMInvalidOutputError("Chat Completions returned no choices")

        choice = response.choices[0]
        content = choice.message.content
        if not content:
            raise LLMInvalidOutputError("Chat Completions returned no text response")

        usage = None
        if response.usage is not None:
            usage = LLMUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        finish_reason = choice.finish_reason
        if finish_reason == "tool_calls":
            finish_reason = "tool_call"
        if finish_reason not in {"stop", "length", "tool_call"}:
            finish_reason = None

        return LLMResponse(
            model=response.model,
            content=content,
            usage=usage,
            latency_ms=(perf_counter() - started_at) * 1000,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _build_messages(request: LLMRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for message in request.messages:
            if message.role not in _SUPPORTED_ROLES:
                raise LLMProviderError(f"unsupported chat message role: {message.role}")
            messages.append({"role": message.role, "content": message.content})

        if request.response_schema is not None:
            schema = json.dumps(
                request.response_schema,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        f"Return only valid JSON matching this JSON Schema exactly: {schema}"
                    ),
                },
            )
        return messages


class OpenAIEmbeddingProvider:
    model_name: str
    dimension: int

    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        model_name: str = "text-embedding-3-small",
        dimension: int = EMBEDDING_DIMENSION,
        timeout_seconds: float = 30.0,
        index_version: str | None = None,
    ) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._client = client or OpenAI()
        self.model_name = model_name
        self.dimension = dimension
        self._timeout_seconds = timeout_seconds
        self.index_version = index_version
        self.last_input_tokens: int | None = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > 1024:
            raise EmbeddingProviderError("Embedding batch exceeds 1024 texts")
        self.last_input_tokens = None
        duration = min(self._timeout_seconds, dependency_timeout.get() or self._timeout_seconds)
        deadline = perf_counter() + duration
        vectors: list[list[float]] = []
        known_usage = True
        tokens = 0
        for start in range(0, len(texts), 16):
            batch = list(texts[start : start + 16])
            remaining = deadline - perf_counter()
            if remaining <= 0:
                raise EmbeddingProviderError("Embedding deadline exceeded") from LLMTimeoutError()

            def request_batch(timeout: float, batch: list[str] = batch) -> Any:
                with span(
                    "embedding.request", model_id=self.model_name, batch_size=len(batch)
                ) as current:
                    try:
                        response = self._client.embeddings.create(
                            model=self.model_name,
                            input=batch,
                            dimensions=self.dimension,
                            encoding_format="float",
                            timeout=timeout,
                        )
                    except Exception as exc:
                        raise EmbeddingProviderError(
                            "OpenAI embedding request failed"
                        ) from _translate_llm_error(exc)
                    usage = getattr(response, "usage", None)
                    if usage is not None:
                        current.set_attribute("input_tokens", usage.prompt_tokens)
                    return response

            response = retry_call(
                request_batch,
                RetryPolicy(max_attempts=2, total_deadline=min(60, remaining)),
            ).value
            ordered = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered] != list(range(len(batch))):
                raise EmbeddingProviderError("Embedding response has invalid item indices")
            vectors.extend(list(item.embedding) for item in ordered)
            usage = getattr(response, "usage", None)
            if usage is None:
                known_usage = False
            else:
                tokens += usage.prompt_tokens
        self.last_input_tokens = tokens if known_usage else None
        return vectors


def _translate_llm_error(error: Exception) -> LLMProviderError:
    if isinstance(error, APITimeoutError):
        return LLMTimeoutError("OpenAI request timed out")
    if isinstance(error, AuthenticationError):
        return LLMAuthenticationError("OpenAI authentication failed")
    if isinstance(error, RateLimitError):
        return LLMRateLimitError("OpenAI rate limit exceeded")
    if isinstance(error, APIConnectionError):
        return LLMProviderUnavailableError("OpenAI is unavailable")
    if isinstance(error, APIStatusError):
        if error.status_code in {500, 502, 503, 504}:
            return LLMProviderUnavailableError("OpenAI is unavailable")
        if error.status_code in {400, 404} and error.code == "model_not_found":
            return LLMUnknownModelError("OpenAI model was not found")
        return LLMProviderError("OpenAI request failed")
    if isinstance(error, LLMProviderError):
        return error
    return LLMProviderError("OpenAI request failed")
