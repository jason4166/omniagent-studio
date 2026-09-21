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
from omniagent.reliability import CircuitBreaker, RetryPolicy, error_code, retry_call, transient
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
        PlatformError(ErrorCode.PROVIDER_RATE_LIMIT),
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
        PlatformError(ErrorCode.DAILY_QUOTA),
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


@pytest.mark.parametrize(
    ("failure", "expected_code", "retryable"),
    [
        (PlatformError(ErrorCode.RATE_LIMIT), ErrorCode.RATE_LIMIT, True),
        (PlatformError(ErrorCode.DAILY_QUOTA), ErrorCode.DAILY_QUOTA, False),
        (LLMRateLimitError("private upstream details"), ErrorCode.PROVIDER_RATE_LIMIT, True),
    ],
)
def test_rate_limit_categories_have_distinct_public_codes(failure, expected_code, retryable):
    code = error_code(failure)
    assert code == expected_code
    assert PlatformError(code).status_code == 429
    assert transient(failure) is retryable
    assert "private upstream details" not in PlatformError(code).message


@pytest.mark.parametrize("prior_failures", [0, 1, 3])
@pytest.mark.parametrize("failure", [PlatformError(ErrorCode.DAILY_QUOTA), TimeoutError()])
def test_local_precheck_failure_preserves_dependency_health_and_does_not_retry(
    prior_failures, failure
):
    clock = Clock()
    circuit = CircuitBreaker(3, 5, clock=clock)
    for _ in range(prior_failures):
        circuit.acquire()
        circuit.finish(LLMTimeoutError())
    clock.wait(5)
    health = (circuit.failures, circuit.opened_at)
    reservations = []

    def reserve():
        reservations.append(1)
        raise failure

    with pytest.raises(type(failure)) as caught:
        retry_call(
            lambda _: pytest.fail("A rejected reservation must not call the provider"),
            RetryPolicy(),
            before_attempt=reserve,
            circuit=circuit,
            clock=clock,
            wait=lambda _: pytest.fail("A local precheck must not retry"),
        )
    assert caught.value is failure
    assert reservations == [1]
    assert (circuit.failures, circuit.opened_at) == health
    # A rejected local reservation must not strand the next eligible dependency probe.
    circuit.acquire()
    if prior_failures == 3:
        with pytest.raises(PlatformError, match="circuit"):
            circuit.acquire()


@pytest.mark.parametrize("was_half_open", [False, True])
def test_slow_local_precheck_cannot_release_another_requests_new_probe(was_half_open):
    clock = Clock()
    circuit = CircuitBreaker(2, 5, clock=clock)
    for _ in range(2 if was_half_open else 1):
        circuit.acquire()
        circuit.finish(LLMTimeoutError())
    clock.wait(5)
    other_probes = []

    def slow_reserve():
        # Another in-flight call fails while this caller is waiting on its local reservation.
        circuit.finish(LLMTimeoutError())
        clock.wait(5)
        other_probes.append(circuit.acquire())
        raise PlatformError(ErrorCode.DAILY_QUOTA)

    with pytest.raises(PlatformError) as caught:
        retry_call(
            lambda _: pytest.fail("The rejected caller must not reach the provider"),
            RetryPolicy(),
            before_attempt=slow_reserve,
            circuit=circuit,
            clock=clock,
            wait=lambda _: pytest.fail("A rejected reservation must not retry"),
        )
    assert caught.value.code == ErrorCode.DAILY_QUOTA
    assert circuit.failures == (3 if was_half_open else 2)
    assert circuit.opened_at == 5
    with pytest.raises(PlatformError, match="circuit"):
        circuit.acquire()
    circuit.abandon(other_probes[0])
    assert circuit.acquire() is not None
