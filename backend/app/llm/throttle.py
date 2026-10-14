"""Client-side rate limiting for model calls.

Free and low-tier API keys allow a limited number of requests per minute. Without throttling,
reading a 27-claim work queue fires 27 calls in a few seconds and the provider answers
"429 Too Many Requests". The throttle spaces calls out so they stay under the configured limit.

One limiter is shared by every request in the process (it wraps the container-level client).
"""
from __future__ import annotations

import threading
import time
from collections import deque

from app.llm.client import LLMClient, LLMResult


class RateLimiter:
    """Sliding 60-second window. acquire() blocks until a slot is free."""

    def __init__(self, per_minute: int, *, clock=time.monotonic, sleep=time.sleep):
        self._limit = max(1, per_minute)
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep

    def acquire(self) -> float:
        """Wait for a slot; returns the seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self._limit:
                    self._calls.append(now)
                    return waited
                pause = 60.0 - (now - self._calls[0]) + 0.05
            self._sleep(pause)
            waited += pause


class ThrottledLLMClient(LLMClient):
    def __init__(self, inner: LLMClient, per_minute: int, limiter: RateLimiter | None = None):
        self._inner = inner
        self._limiter = limiter or RateLimiter(per_minute)
        self.name = inner.name
        self.per_minute = per_minute

    @property
    def inner(self) -> LLMClient:
        return self._inner

    def structured(self, **kwargs) -> LLMResult:
        self._limiter.acquire()
        return self._inner.structured(**kwargs)
