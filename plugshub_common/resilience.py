"""Standard resilience: retry, timeout, circuit breaker (SaaS Constitution Article XXVI §3).

The fleet-standard defaults for talking to anything that can fail (Article VIII §1, XXVI §3). These
primitives are dependency-free and are reused by :mod:`plugshub_common.clients` so every service
retries, times out, and trips its breaker the same way — a failed dependency degrades a feature
instead of crashing the service (XXVI §3).

State machine of :class:`CircuitBreaker`:

* ``closed``    — calls flow; consecutive failures count toward the trip threshold.
* ``open``      — calls are refused immediately (fail-fast) until the recovery window elapses.
* ``half_open`` — a limited number of trial calls probe recovery; enough successes close it, any
  failure re-opens it.
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Tuple, Type, TypeVar

__all__ = [
    "RetryPolicy",
    "TimeoutPolicy",
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "compute_backoff",
    "retry_async",
]

T = TypeVar("T")


class CircuitBreakerOpen(RuntimeError):
    """Raised when a call is refused because the breaker is open (Article XXVI §3)."""


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential-backoff retry policy with jitter (Article VIII §1).

    ``max_attempts`` counts the *total* tries (1 = no retry). Delay grows
    ``base_delay * multiplier**(attempt-1)``, capped at ``max_delay``; full jitter avoids retry
    storms. Only ``retry_on`` exception types are retried — everything else propagates immediately.
    """

    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 5.0
    multiplier: float = 2.0
    jitter: bool = True
    retry_on: Tuple[Type[BaseException], ...] = (Exception,)


@dataclass(frozen=True)
class TimeoutPolicy:
    """Per-attempt timeouts, in seconds (Article VIII §1)."""

    connect: float = 3.0
    total: float = 10.0


@dataclass
class CircuitBreaker:
    """A three-state circuit breaker (Article XXVI §3).

    ``failure_threshold`` consecutive failures trip it open; after ``recovery_timeout`` seconds it
    goes half-open and admits trial calls; ``success_threshold`` consecutive successes close it. A
    monotonic clock is injectable (``_clock``) so tests are deterministic.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    success_threshold: int = 1
    name: str = "default"
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    _state: str = field(default="closed", init=False)
    _failures: int = field(default=0, init=False)
    _successes: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)

    @property
    def state(self) -> str:
        """Current state, transitioning ``open`` → ``half_open`` when the window has elapsed."""
        if self._state == "open" and self._clock() - self._opened_at >= self.recovery_timeout:
            self._state = "half_open"
            self._successes = 0
        return self._state

    def allow(self) -> bool:
        """Whether a call may proceed right now (fail-fast when open)."""
        return self.state != "open"

    def record_success(self) -> None:
        """Record a successful call; enough in a row close a half-open breaker."""
        if self._state == "half_open":
            self._successes += 1
            if self._successes >= self.success_threshold:
                self._reset()
        else:
            self._failures = 0

    def record_failure(self) -> None:
        """Record a failed call; trip open on threshold, or immediately from half-open."""
        if self._state == "half_open":
            self._trip()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = "open"
        self._opened_at = self._clock()
        self._successes = 0

    def _reset(self) -> None:
        self._state = "closed"
        self._failures = 0
        self._successes = 0


def compute_backoff(attempt: int, policy: RetryPolicy) -> float:
    """Delay in seconds before ``attempt`` (1-indexed), with cap and optional full jitter."""
    raw = policy.base_delay * (policy.multiplier ** max(0, attempt - 1))
    capped = min(raw, policy.max_delay)
    if policy.jitter:
        return random.uniform(0, capped)
    return capped


async def retry_async(
    func: Callable[[], Awaitable[T]],
    policy: Optional[RetryPolicy] = None,
    breaker: Optional[CircuitBreaker] = None,
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    """Run an async callable with retry + optional circuit breaker (Article VIII §1, XXVI §3).

    Refuses immediately with :class:`CircuitBreakerOpen` when the breaker is open. On a retryable
    exception it backs off (:func:`compute_backoff`) and retries up to ``policy.max_attempts``,
    recording success/failure into the breaker. The last exception propagates when attempts are
    exhausted.
    """
    policy = policy or RetryPolicy()
    last_exc: Optional[BaseException] = None

    for attempt in range(1, policy.max_attempts + 1):
        if breaker is not None and not breaker.allow():
            raise CircuitBreakerOpen("circuit '{}' is open".format(breaker.name))
        try:
            result = await func()
        except policy.retry_on as exc:
            last_exc = exc
            if breaker is not None:
                breaker.record_failure()
            if attempt >= policy.max_attempts:
                break
            await sleep(compute_backoff(attempt + 1, policy))
        else:
            if breaker is not None:
                breaker.record_success()
            return result

    assert last_exc is not None
    raise last_exc
