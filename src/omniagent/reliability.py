"""Bounded retries with explicit transient classification and idempotency requirements."""

import random
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError

from omniagent.errors import ErrorCode, PlatformError
from omniagent.llm import (
    LLMAuthenticationError,
    LLMInvalidOutputError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnknownModelError,
)
from omniagent.telemetry import span
from omniagent.tooling import ToolBusinessError

dependency_timeout: ContextVar[float | None] = ContextVar("dependency_timeout", default=None)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_attempts: int = Field(default=3, ge=1, le=4)
    base_delay: float = Field(default=0.1, ge=0, le=2)
    max_delay: float = Field(default=1, ge=0, le=5)
    jitter: float = Field(default=0.2, ge=0, le=1)
    total_deadline: float = Field(default=20, gt=0, le=60)


def transient(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            LLMTimeoutError,
            LLMRateLimitError,
            LLMProviderUnavailableError,
            httpx.TimeoutException,
            httpx.NetworkError,
            TimeoutError,
            ConnectionError,
            DatabaseTimeoutError,
        ),
    ):
        return True
    if isinstance(exc, OperationalError):
        return bool(
            exc.connection_invalidated
            or getattr(exc.orig, "sqlstate", None)
            in {"08003", "08006", "40001", "40P01", "57P01", "57014"}
        )
    if isinstance(exc, PlatformError):
        return exc.code in {
            ErrorCode.TIMEOUT,
            ErrorCode.RATE_LIMIT,
            ErrorCode.UNAVAILABLE,
            ErrorCode.CIRCUIT_OPEN,
        }
    if isinstance(exc, ToolBusinessError):
        return exc.code in {
            "tool_timeout",
            "http_timeout",
            "http_unavailable",
            "http_429",
            "http_500",
            "http_502",
            "http_503",
            "http_504",
            "mcp_timeout",
            "mcp_unavailable",
        }
    return False


def error_code(exc: Exception) -> ErrorCode:
    if isinstance(exc, PlatformError):
        return exc.code
    if isinstance(exc, LLMAuthenticationError):
        return ErrorCode.AUTH
    if isinstance(exc, LLMUnknownModelError):
        return ErrorCode.NOT_FOUND
    if isinstance(exc, LLMInvalidOutputError):
        return ErrorCode.BAD_RESPONSE
    if isinstance(
        exc, (LLMTimeoutError, TimeoutError, httpx.TimeoutException, DatabaseTimeoutError)
    ):
        return ErrorCode.TIMEOUT
    if isinstance(exc, LLMRateLimitError):
        return ErrorCode.RATE_LIMIT
    if isinstance(exc, ToolBusinessError) and "timeout" in exc.code:
        return ErrorCode.TIMEOUT
    if isinstance(exc, SQLAlchemyError) or transient(exc):
        return ErrorCode.UNAVAILABLE
    return ErrorCode.BAD_RESPONSE


class CircuitBreaker:
    def __init__(
        self, threshold: int = 3, cooldown: float = 15, *, clock: Callable[[], float] = monotonic
    ) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self.probing = False
        self.lock = Lock()

    def acquire(self) -> None:
        with self.lock:
            if self.opened_at is not None:
                if self.clock() - self.opened_at < self.cooldown or self.probing:
                    raise PlatformError(ErrorCode.CIRCUIT_OPEN)
                self.probing = True

    def finish(self, error: BaseException | None) -> None:
        with self.lock:
            self.probing = False
            if error is None or not transient(error):
                self.failures = 0
                self.opened_at = None
            else:
                self.failures += 1
                if self.failures >= self.threshold:
                    self.opened_at = self.clock()


@dataclass(frozen=True)
class RetryResult[T]:
    value: T
    attempts: int


def retry_call[T](
    operation: Callable[[float], T],
    policy: RetryPolicy,
    *,
    circuit: CircuitBreaker | None = None,
    write: bool = False,
    idempotency_key: str | None = None,
    before_attempt: Callable[[], None] | None = None,
    clock: Callable[[], float] = monotonic,
    wait: Callable[[float], None] = sleep,
    noise: Callable[[], float] = random.random,
) -> RetryResult[T]:
    deadline = clock() + policy.total_deadline
    last: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            raise PlatformError(ErrorCode.TIMEOUT) from last
        if circuit:
            circuit.acquire()
        try:
            if before_attempt:
                before_attempt()
            with span("dependency.attempt", attempt=attempt, retry_count=attempt - 1):
                result = operation(remaining)
            if clock() > deadline:
                raise PlatformError(ErrorCode.TIMEOUT)
        except Exception as exc:
            if circuit:
                circuit.finish(exc)
            last = exc
            if (
                not transient(exc)
                or attempt == policy.max_attempts
                or (write and not idempotency_key)
            ):
                raise
            delay = min(policy.max_delay, policy.base_delay * 2 ** (attempt - 1)) * (
                1 + policy.jitter * noise()
            )
            if clock() + delay >= deadline:
                raise PlatformError(ErrorCode.TIMEOUT) from exc
            wait(delay)
        else:
            if circuit:
                circuit.finish(None)
            return RetryResult(result, attempt)
    raise PlatformError(ErrorCode.UNAVAILABLE) from last
