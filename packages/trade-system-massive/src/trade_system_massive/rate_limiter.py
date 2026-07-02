"""A token-bucket rate limiter for the Massive.com REST API.

The Massive.com free tier enforces a per-minute request budget. All REST calls
pass through this limiter so the adapter stays under budget regardless of how
many concurrent requests the Nautilus data engine issues.

The limiter is an async token bucket: tokens accrue continuously at
``rate`` tokens/second up to ``burst``. ``acquire`` awaits until a token is
available, then consumes it. ``penalize`` drains the bucket and schedules a
``Retry-After`` style cooldown on HTTP 429 responses.
"""

import asyncio
import time


class TokenBucketRateLimiter:
    """An async token-bucket rate limiter.

    Parameters
    ----------
    rate : float
        The sustained refill rate in tokens per second.
    burst : int
        The maximum bucket capacity (instantaneous burst allowance).
    clock : object, optional
        An optional clock exposing ``timestamp()`` returning ``float`` seconds.
        Defaults to ``time.monotonic``.

    """

    def __init__(self, rate: float, burst: int, clock=None) -> None:
        if rate <= 0:
            raise ValueError(f"`rate` must be positive, was {rate}")
        if burst < 1:
            raise ValueError(f"`burst` must be >= 1, was {burst}")

        self._rate = float(rate)
        self._burst = float(burst)
        self._tokens = float(burst)
        self._lock = asyncio.Lock()
        self._clock = clock
        self._last = self._now()
        # A scheduled cooldown (seconds since epoch) until which all acquires block.
        self._penalty_until = 0.0

    @property
    def rate(self) -> float:
        """The sustained refill rate in tokens per second."""
        return self._rate

    @property
    def burst(self) -> int:
        """The maximum burst capacity."""
        return int(self._burst)

    def _now(self) -> float:
        if self._clock is not None and hasattr(self._clock, "timestamp"):
            return float(self._clock.timestamp())
        return time.monotonic()

    def _refill(self) -> None:
        now = self._now()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` are available, then consume them.

        Parameters
        ----------
        tokens : float, default 1.0
            The number of tokens to consume.

        """
        if tokens > self._burst:
            raise ValueError(
                f"requested {tokens} tokens exceeds burst capacity {self._burst}",
            )

        async with self._lock:
            while True:
                self._refill()

                # Honour any active 429 penalty first.
                now = self._now()
                if now < self._penalty_until:
                    await asyncio.sleep(self._penalty_until - now)
                    continue

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                # Compute wait time for enough tokens to accrue.
                deficit = tokens - self._tokens
                await asyncio.sleep(deficit / self._rate)

    def penalize(self, retry_after: float) -> None:
        """Schedule a cooldown that blocks all subsequent acquires.

        Called when the upstream API returns HTTP 429. ``retry_after`` is the
        number of seconds to wait (from the response's ``Retry-After`` header
        or a backoff estimate). Also drains the bucket so the sustained rate
        is respected once the cooldown lifts.

        Parameters
        ----------
        retry_after : float
            Seconds to wait before issuing further requests.

        """
        if retry_after < 0:
            retry_after = 0.0
        self._penalty_until = self._now() + retry_after
        self._tokens = 0.0


def rate_per_min_to_per_sec(rate_per_min: float) -> float:
    """Convert a per-minute rate to a per-second rate."""
    return rate_per_min / 60.0
