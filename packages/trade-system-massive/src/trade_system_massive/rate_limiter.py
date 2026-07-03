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

from massive.exceptions import BadResponse


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
        """Initialize the bucket full of tokens at the given refill rate."""
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


async def rate_limited_call(
    limiter: TokenBucketRateLimiter,
    fn,
    /,
    *args,
    max_retries: int = 3,
    **kwargs,
):
    """Run a synchronous Massive ``RESTClient`` method under the rate limiter.

    Acquires a token from `limiter`, then runs ``fn(*args, **kwargs)`` in a worker
    thread (the Massive client is synchronous / urllib3-based). The Massive client
    already retries ``429``/``5xx`` internally via ``urllib3.util.Retry``; a
    :class:`massive.exceptions.BadResponse` here means those retries were exhausted.
    Because ``BadResponse`` carries only the response body (no status code), we treat
    any such failure as transient: inspect the body for a rate-limit hint and, when
    found, schedule a limiter cooldown via :meth:`penalize`; then back off and retry up
    to ``max_retries`` times.

    Parameters
    ----------
    limiter : TokenBucketRateLimiter
        The token-bucket limiter gating this adapter's REST traffic.
    fn : callable
        The synchronous Massive client method to call.
    *args, **kwargs
        Forwarded to ``fn``.
    max_retries : int, default 3
        The number of times to retry after a ``BadResponse`` before re-raising.

    Returns:
    -------
    Any
        Whatever ``fn`` returns.

    Raises:
    ------
    BadResponse
        If the call still fails after ``max_retries`` retries.

    """
    last_exc: BadResponse | None = None
    for attempt in range(max_retries + 1):
        await limiter.acquire()
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BadResponse as exc:
            last_exc = exc
            body = str(exc.args[0]) if exc.args else ""
            if "rate limit" in body.lower() or "429" in body:
                # Server says we are too fast: drain the bucket and cool down.
                limiter.penalize(retry_after=2.0**attempt)
            if attempt >= max_retries:
                break
            await asyncio.sleep(2.0**attempt)
    assert last_exc is not None  # pragma: no cover - loop always sets it before break
    raise last_exc
