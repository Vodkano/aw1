"""Limitador por cliente con ventana deslizante, en memoria."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_minute: int, window: float = 60.0) -> None:
        self._limit = per_minute
        self._window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    def allow(self, key: str, *, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        moment = time.monotonic() if now is None else now
        bucket = self._hits[key]
        while bucket and bucket[0] <= moment - self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(moment)
        return True

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        bucket = self._hits.get(key)
        if not bucket:
            return 1
        moment = time.monotonic() if now is None else now
        return max(1, int(self._window - (moment - bucket[0])) + 1)
