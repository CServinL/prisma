"""Generic in-process rate limiter — not source-specific.

Every source in `prisma/integrations/sources/` owns one instance of this,
configured with that source's real published quota. This is intentionally
NOT the supervisor's resource_lock.py/ResourceManager pattern (HTTP-based
cross-process leasing for the GPU compute pools) — every caller of
SearchAgent (coordinator.py, stream_runner.py, research_stream_manager.py)
only ever runs inside the single `api` worker process, so there's no
cross-process contention to arbitrate, only two same-process call paths
(the background stream scheduler thread and on-demand API requests)
sharing one quota. A thread-safe token bucket is sufficient and avoids
the network round-trip and fail-open complexity the supervisor pattern
needs for its harder problem.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


class RateLimiter:
    """Token-bucket rate limiter with an optional hard daily cap.

    `requests_per_second` refills the bucket continuously (burst capacity
    is always 1 — sources here are called in a simple sequential loop, not
    bursts, so smoothing to a steady rate is what matches each API's real
    published guidance). `daily_cap`, if set, is a separate hard ceiling
    tracked by UTC calendar day — for quotas like Google Books' 10,000
    requests/day, where waiting for a fresh token would mean waiting up to
    a whole day, so a denial should surface immediately instead of via a
    long block.
    """

    def __init__(self, requests_per_second: float, daily_cap: int | None = None):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        self._interval = 1.0 / requests_per_second
        self._daily_cap = daily_cap

        self._lock = threading.Lock()
        self._next_allowed = time.monotonic()

        self._day: str | None = None
        self._day_count = 0

    def _daily_cap_available(self) -> bool:
        """Must be called with self._lock held. Returns False only when
        daily_cap is set and already exhausted for the current UTC day —
        otherwise increments today's counter and returns True."""
        if self._daily_cap is None:
            return True
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self._day_count = 0
        if self._day_count >= self._daily_cap:
            return False
        self._day_count += 1
        return True

    def acquire(self, timeout: float = 30.0) -> bool:
        """Blocks until a token is free or `timeout` seconds elapse.
        Returns False immediately (no waiting) if the daily cap is already
        exhausted — waiting for a day-boundary reset is never the right
        behavior for a caller. Returns False if `timeout` elapses first.
        Callers should treat False the same as a failed/unreachable source
        today: log a warning and skip it for this search, not raise."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next_allowed:
                    # Only consume daily budget once we're actually about to
                    # grant — checking it on every retry-loop iteration would
                    # double-consume it for a single logical acquire() call.
                    if not self._daily_cap_available():
                        return False
                    self._next_allowed = now + self._interval
                    return True
                wait = self._next_allowed - now
            remaining = deadline - time.monotonic()
            if wait > remaining:
                return False
            time.sleep(min(wait, remaining))
