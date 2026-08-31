from typing import Literal, Protocol, Self

from pydantic import BaseModel, Field, ValidationError, model_validator


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMRequest(BaseModel):
    model: str
    messages: list[LLMMessage]
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    response_schema: dict[str, object] | None = None


class LLMUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class LLMResponse(BaseModel):
    model: str
    content: str
    usage: LLMUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
    finish_reason: Literal["stop", "length", "tool_call"] | None = None


class RouteDecision(BaseModel):
    route: Literal["direct", "retrieve", "tool", "clarify"]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    output_text: str | None = None
    tool_name: str | None = None
    args: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_something(self) -> Self:
        if self.route == "tool" and (self.tool_name is None or self.args is None):
            raise ValueError("tool_name和args不能为空")
        if self.route != "tool" and (self.tool_name is not None or self.args is not None):
            raise ValueError("不调用工具时不能有tool_name或args")
        return self


class LLMProviderError(RuntimeError):
    pass


class LLMTimeoutError(LLMProviderError):
    pass


class LLMUnknownModelError(LLMProviderError):
    pass


class LLMInvalidOutputError(LLMProviderError):
    pass


class LLMRateLimitError(LLMProviderError):
    pass


class LLMAuthenticationError(LLMProviderError):
    pass


class LLMProviderUnavailableError(LLMProviderError):
    pass


def parse_route_decision(response: LLMResponse) -> RouteDecision:
    try:
        return RouteDecision.model_validate_json(response.content)
    except ValidationError as exc:
        raise LLMInvalidOutputError from exc


class LLMProvider(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse: ...


class FakeLLM:
    def __init__(self, response: LLMResponse, error: LLMProviderError | None = None) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []
        self.error = error

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.model != self.response.model:
            raise LLMUnknownModelError
        if self.error is not None:
            raise self.error
        return self.response
