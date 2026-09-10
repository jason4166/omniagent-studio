import httpx
import pytest

from omniagent.errors import ErrorCode, PlatformError
from omniagent.llm import (
    LLMAuthenticationError,
    LLMInvalidOutputError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnknownModelError,
)
from omniagent.reliability import CircuitBreaker, RetryPolicy, retry_call
from omniagent.tooling import ToolBusinessError

pytestmark = pytest.mark.unit


class Clock:
    value = 0.0

    def __call__(self):
        return self.value

    def wait(self, delay):
        self.value += delay


@pytest.mark.parametrize(
    "failure",
    [
        LLMTimeoutError(),
        LLMRateLimitError(),
        LLMProviderUnavailableError(),
        httpx.ReadTimeout("timeout"),
        httpx.ConnectError("network"),
        ToolBusinessError("http_429", "busy"),
        ToolBusinessError("http_503", "down"),
        ToolBusinessError("mcp_unavailable", "down"),
        TimeoutError(),
        PlatformError(ErrorCode.UNAVAILABLE),
    ],
)
def test_transient_faults_retry_with_reservations_and_deadline(failure):
    clock = Clock()
    calls = []
    reservations = []

    def operation(remaining):
        calls.append(remaining)
        if len(calls) < 3:
            raise failure
        return "recovered"

    result = retry_call(
        operation,
        RetryPolicy(base_delay=0.1, jitter=0.5),
        clock=clock,
        wait=clock.wait,
        noise=lambda: 1,
        before_attempt=lambda: reservations.append(1),
    )
    assert result.value == "recovered" and result.attempts == 3
    assert len(reservations) == 3
    assert clock.value == pytest.approx(0.45)
    assert calls == sorted(calls, reverse=True)


@pytest.mark.parametrize(
    "failure",
    [
        LLMAuthenticationError(),
        LLMUnknownModelError(),
        LLMInvalidOutputError(),
        PlatformError(ErrorCode.PERMISSION),
        PlatformError(ErrorCode.VALIDATION),
        ToolBusinessError("http_404", "absent"),
        ToolBusinessError("http_501", "unsupported"),
        ToolBusinessError("mcp_schema", "invalid"),
    ],
)
def test_permanent_errors_never_retry(failure):
    attempts = []

    def operation(_remaining):
        attempts.append(1)
        raise failure

    with pytest.raises(type(failure)):
        retry_call(operation, RetryPolicy(), wait=lambda _delay: pytest.fail("retry forbidden"))
    assert len(attempts) == 1


def test_write_retry_requires_idempotency_and_is_bounded():
    calls = []

    def operation(_remaining):
        calls.append(1)
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        retry_call(operation, RetryPolicy(), write=True)
    assert len(calls) == 1
    with pytest.raises(TimeoutError):
        retry_call(
            operation,
            RetryPolicy(),
            write=True,
            idempotency_key="approved-operation",
            wait=lambda _: None,
        )
    assert len(calls) == 4


def test_total_deadline_and_circuit_half_open_have_no_unbounded_loops():
    clock = Clock()
    circuit = CircuitBreaker(2, 5, clock=clock)
    for _ in range(2):
        circuit.acquire()
        circuit.finish(TimeoutError())
    with pytest.raises(PlatformError, match="circuit"):
        circuit.acquire()
    clock.wait(5)
    circuit.acquire()
    with pytest.raises(PlatformError):
        circuit.acquire()
    circuit.finish(None)
    circuit.acquire()

    def too_slow(_remaining):
        clock.wait(3)
        return "late"

    with pytest.raises(PlatformError, match="timeout"):
        retry_call(too_slow, RetryPolicy(total_deadline=2), clock=clock, wait=clock.wait)
