"""Small in-memory rate limiter (single-instance API)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            bucket = [stamp for stamp in self._buckets[key] if stamp > cutoff]
            allowed = len(bucket) < limit
            if allowed:
                bucket.append(now)
            self._buckets[key] = bucket
            remaining = max(0, limit - len(bucket))
        return allowed, remaining, int(now + window_seconds)


limiter = RateLimiter()
