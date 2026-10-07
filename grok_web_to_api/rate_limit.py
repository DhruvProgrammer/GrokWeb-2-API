"""Per-IP fixed-window rate limiter, in-memory.

For a single-instance deployment this is sufficient. For multi-replica
deployments, swap for Redis (or any shared store) - left as a TODO.

We expose a `slowapi.Limiter`-compatible interface so the same module
can be replaced without touching the route handlers.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Tuple


class RateLimiter:
    """Fixed-window token bucket, keyed by client IP."""

    def __init__(self, window_seconds: int, max_requests: int):
        self.window = window_seconds
        self.max = max_requests
        self._lock = threading.Lock()
        # Map[ip] = list of request times within the current window.
        self._buckets: Dict[str, List[float]] = {}

    def check(self, ip: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        import time

        now = time.time()
        cutoff = now - self.window

        with self._lock:
            timestamps = self._buckets.get(ip, [])
            # Drop expired entries.
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self.max:
                # Retry-after = seconds until the oldest in-window entry expires.
                retry_after = max(1, int(self.window - (now - timestamps[0])))
                self._buckets[ip] = timestamps  # still save the cleanup
                return False, retry_after

            timestamps.append(now)
            self._buckets[ip] = timestamps

            # Opportunistic GC so memory doesn't grow unbounded.
            if len(self._buckets) > 10_000:
                self._buckets.clear()

            return True, 0