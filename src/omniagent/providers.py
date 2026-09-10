"""Explicit real-provider fallback; Fake is never a fallback for a real provider."""

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from openai import OpenAI

from omniagent.credentials import resolve_secret
from omniagent.demo_provider import DemoProvider
from omniagent.errors import ErrorCode, PlatformError
from omniagent.llm import LLMInvalidOutputError, LLMProvider, LLMRequest, LLMResponse, LLMUsage
from omniagent.openai_adapters import OpenAICompatibleChatProvider
from omniagent.profiles import AgentProfile
from omniagent.reliability import CircuitBreaker, RetryPolicy, retry_call, transient
from omniagent.telemetry import span

model_attempt: ContextVar[Callable[[], None] | None] = ContextVar("model_attempt", default=None)
model_usage: ContextVar[Callable[[LLMUsage | None], None] | None] = ContextVar(
    "model_usage", default=None
)


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    provider: LLMProvider
    model: str | None = None


class ControlledProvider:
    def __init__(
        self, bindings: list[ProviderBinding], circuits: dict[str, CircuitBreaker] | None = None
    ) -> None:
        if not 1 <= len(bindings) <= 2:
            raise ValueError("At most two explicitly configured providers are supported")
        if len(bindings) > 1 and any(b.provider_id == "fake" for b in bindings):
            raise ValueError("Fake cannot participate in a real-provider fallback chain")
        self.bindings = bindings
        self.circuits = (
            circuits
            if circuits is not None
            else {b.provider_id: CircuitBreaker() for b in bindings}
        )
        self.last: dict[str, object] = {}

    def generate(self, request: LLMRequest) -> LLMResponse:
        deadline = monotonic() + request.timeout_seconds
        failure: Exception | None = None
        for index, binding in enumerate(self.bindings):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PlatformError(ErrorCode.TIMEOUT) from failure
            model = binding.model or request.model

            def attempt(
                seconds: float,
                binding: ProviderBinding = binding,
                model: str = model,
                index: int = index,
            ) -> LLMResponse:
                with span(
                    "llm", provider_id=binding.provider_id, model_id=model, degraded=index > 0
                ) as current:
                    response = binding.provider.generate(
                        request.model_copy(
                            update={
                                "model": model,
                                "timeout_seconds": min(seconds, deadline - monotonic()),
                            }
                        )
                    )
                    current.set_attribute("requested_model_id", model)
                    current.set_attribute("model_id", response.model)
                    record = model_usage.get()
                    if record is not None:
                        record(response.usage)
                    if len(response.content.encode()) > 16000:
                        raise LLMInvalidOutputError("Model response exceeded its size limit")
                    if request.response_schema is not None:
                        try:
                            Draft202012Validator(request.response_schema).validate(
                                json.loads(response.content)
                            )
                        except (ValueError, ValidationError) as exc:
                            raise LLMInvalidOutputError(
                                "Model response failed schema validation"
                            ) from exc
                    if response.usage:
                        current.set_attribute("input_tokens", response.usage.input_tokens)
                        current.set_attribute("output_tokens", response.usage.output_tokens)
                        current.set_attribute("total_tokens", response.usage.total_tokens)
                    return response

            try:
                result = retry_call(
                    attempt,
                    RetryPolicy(max_attempts=2, total_deadline=min(remaining, 15)),
                    circuit=self.circuits[binding.provider_id],
                    before_attempt=model_attempt.get(),
                )
            except Exception as exc:
                failure = exc
                if not transient(exc) or index + 1 == len(self.bindings):
                    raise
            else:
                self.last = {
                    "provider_id": binding.provider_id,
                    "model_id": result.value.model,
                    "degraded": index > 0,
                    "retry_count": result.attempts - 1,
                }
                return result.value
        raise PlatformError(ErrorCode.UNAVAILABLE) from failure


@contextmanager
def configured_provider(
    profile: AgentProfile, override: LLMProvider | None, circuits: dict[str, CircuitBreaker]
) -> Iterator[ControlledProvider]:
    clients: list[OpenAI] = []
    bindings: list[ProviderBinding] = []
    try:
        if override is not None or profile.provider_id == "fake":
            bindings = [
                ProviderBinding(
                    "fake" if profile.provider_id == "fake" else "primary",
                    override or DemoProvider(),
                )
            ]
        else:
            if profile.provider_id not in {"primary", "primary-with-fallback"}:
                raise PlatformError(ErrorCode.VALIDATION, "Unknown provider reference")
            for provider_id, prefix in [
                ("primary", "OMNIAGENT_PROVIDER"),
                *(
                    [("secondary", "OMNIAGENT_FALLBACK")]
                    if profile.provider_id == "primary-with-fallback"
                    else []
                ),
            ]:
                key = resolve_secret(prefix)
                endpoint = os.environ.get(prefix + "_BASE_URL")
                if not key or not endpoint:
                    raise PlatformError(
                        ErrorCode.UNAVAILABLE, "Optional provider is not configured"
                    )
                client = OpenAI(api_key=key, base_url=endpoint, timeout=15, max_retries=0)
                clients.append(client)
                model = (
                    profile.model if provider_id == "primary" else os.environ.get(prefix + "_MODEL")
                )
                if not model:
                    raise PlatformError(ErrorCode.VALIDATION, "Fallback model is not configured")
                bindings.append(
                    ProviderBinding(
                        provider_id,
                        OpenAICompatibleChatProvider(
                            client, thinking=os.environ.get(prefix + "_THINKING")
                        ),
                        model,
                    )
                )
        yield ControlledProvider(bindings, circuits)
    finally:
        for client in clients:
            client.close()
