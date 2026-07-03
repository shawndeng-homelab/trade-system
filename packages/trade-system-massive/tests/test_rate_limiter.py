"""Tests for the token-bucket rate limiter and ``rate_limited_call`` retry logic.

Async behaviour is driven through ``asyncio.run`` from synchronous test functions so the
suite needs no ``pytest-asyncio`` plugin.
"""

import asyncio

import pytest
from massive.exceptions import BadResponse
from trade_system_massive.rate_limiter import TokenBucketRateLimiter
from trade_system_massive.rate_limiter import rate_limited_call
from trade_system_massive.rate_limiter import rate_per_min_to_per_sec


class _FakeClock:
    """A controllable monotonic clock for deterministic limiter timing."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def timestamp(self) -> float:
        return self._t

    def advance(self, secs: float) -> None:
        self._t += secs


class _CountingFn:
    """A callable that fails N times with a rate-limit BadResponse, then succeeds."""

    def __init__(self, fail_times: int, result: str = "ok") -> None:
        self._fail_times = fail_times
        self._result = result
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise BadResponse('{"message":"rate limit exceeded"}')
        return self._result


def _no_sleep():
    """Patch ``asyncio.sleep`` to a no-op so retry backoff doesn't slow the tests."""

    async def _fast(_secs):
        return None

    return _fast


# --- token bucket ---------------------------------------------------------------------


def test_rate_per_min_to_per_sec() -> None:
    """5 calls/min converts to 1/12 calls/sec."""
    assert rate_per_min_to_per_sec(5.0) == pytest.approx(5.0 / 60.0)


def test_limiter_rejects_non_positive_rate() -> None:
    """A non-positive rate raises ValueError."""
    with pytest.raises(ValueError, match="rate"):
        TokenBucketRateLimiter(rate=0.0, burst=5)


def test_limiter_rejects_zero_burst() -> None:
    """A zero burst raises ValueError."""
    with pytest.raises(ValueError, match="burst"):
        TokenBucketRateLimiter(rate=1.0, burst=0)


def test_acquire_consumes_tokens_then_refills() -> None:
    """A full bucket yields immediately; tokens refill as time passes."""

    async def scenario() -> None:
        clock = _FakeClock()
        limiter = TokenBucketRateLimiter(rate=1.0, burst=2, clock=clock)
        # Burst of 2 -> two immediate acquires, no waiting.
        await asyncio.wait_for(limiter.acquire(), timeout=1.0)
        await asyncio.wait_for(limiter.acquire(), timeout=1.0)
        # Advance time so one token refills.
        clock.advance(1.0)
        await asyncio.wait_for(limiter.acquire(), timeout=1.0)

    asyncio.run(scenario())


# --- rate_limited_call ----------------------------------------------------------------


def test_rate_limited_call_retries_on_rate_limit_then_succeeds() -> None:
    """A rate-limit BadResponse is retried up to max_retries, then the result returns."""
    limiter = TokenBucketRateLimiter(rate=1000.0, burst=10)
    fn = _CountingFn(fail_times=2)
    original_sleep = asyncio.sleep
    asyncio.sleep = _no_sleep()
    try:
        result = asyncio.run(rate_limited_call(limiter, fn, max_retries=3))
    finally:
        asyncio.sleep = original_sleep

    assert result == "ok"
    assert fn.calls == 3


def test_rate_limited_call_raises_after_exhausting_retries() -> None:
    """When retries are exhausted, the last BadResponse is re-raised."""
    limiter = TokenBucketRateLimiter(rate=1000.0, burst=10)
    fn = _CountingFn(fail_times=10)  # always fails
    original_sleep = asyncio.sleep
    asyncio.sleep = _no_sleep()
    try:
        with pytest.raises(BadResponse):
            asyncio.run(rate_limited_call(limiter, fn, max_retries=2))
    finally:
        asyncio.sleep = original_sleep

    # max_retries=2 -> initial + 2 retries = 3 calls.
    assert fn.calls == 3


def test_rate_limited_call_passes_args_through() -> None:
    """Positional and keyword args are forwarded to the wrapped function."""

    def add(a, b, *, c):
        return a + b + c

    limiter = TokenBucketRateLimiter(rate=1000.0, burst=5)
    result = asyncio.run(rate_limited_call(limiter, add, 1, 2, c=3))
    assert result == 6
