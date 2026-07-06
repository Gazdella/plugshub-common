import pytest

from plugshub_common.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RetryPolicy,
    compute_backoff,
    retry_async,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_backoff_grows_and_caps():
    policy = RetryPolicy(base_delay=1.0, multiplier=2.0, max_delay=5.0, jitter=False)
    assert compute_backoff(1, policy) == 1.0
    assert compute_backoff(2, policy) == 2.0
    assert compute_backoff(10, policy) == 5.0


def test_breaker_trips_and_recovers():
    clock = _Clock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10, success_threshold=1, _clock=clock)
    assert cb.allow()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open" and not cb.allow()
    clock.t = 11
    assert cb.state == "half_open" and cb.allow()
    cb.record_success()
    assert cb.state == "closed"


def test_breaker_reopens_on_half_open_failure():
    clock = _Clock()
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=5, _clock=clock)
    cb.record_failure()
    assert cb.state == "open"
    clock.t = 6
    assert cb.state == "half_open"
    cb.record_failure()
    assert cb.state == "open"


async def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "ok"

    async def no_sleep(_):
        return None

    result = await retry_async(flaky, RetryPolicy(max_attempts=3), sleep=no_sleep)
    assert result == "ok" and attempts["n"] == 3


async def test_retry_exhausts_and_raises():
    async def always_fail():
        raise ValueError("nope")

    async def no_sleep(_):
        return None

    with pytest.raises(ValueError):
        await retry_async(always_fail, RetryPolicy(max_attempts=2), sleep=no_sleep)


async def test_retry_refuses_when_breaker_open():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1000)
    cb.record_failure()  # trip open

    async def fn():
        return "x"

    with pytest.raises(CircuitBreakerOpen):
        await retry_async(fn, RetryPolicy(max_attempts=2), cb)
