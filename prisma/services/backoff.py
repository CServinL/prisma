"""Generic retry/backoff helper.

Not specific to compute-pool leases: any operation that can be transiently
unavailable (a busy resource, a flaky call, a lock someone else holds) should
reuse this instead of hand-rolling its own sleep loop. resource_lock.lease()
is the first caller, retrying a denied acquire() before giving up.
"""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_with_backoff(
    attempt: Callable[[], T],
    is_success: Callable[[T], bool],
    *,
    max_wait: float = 10.0,
    base_delay: float = 0.25,
    max_delay: float = 2.0,
    jitter: float = 0.2,
) -> T:
    """Call `attempt()` until `is_success(result)` is True or `max_wait`
    seconds have elapsed since the first call. Delay between attempts starts
    at `base_delay`, doubles each time up to `max_delay`, and is randomized
    by +/- `jitter` fraction so concurrent callers don't retry in lockstep
    (thundering herd on the same busy resource).

    Always calls `attempt()` at least once. Returns the last result
    regardless of outcome — callers decide what "still failing after
    max_wait" means for them (e.g. resource_lock.lease() yields granted=False).
    """
    start = time.monotonic()
    delay = base_delay
    result = attempt()
    while not is_success(result):
        elapsed = time.monotonic() - start
        if elapsed >= max_wait:
            return result
        sleep_for = min(delay, max_delay, max_wait - elapsed)
        sleep_for *= 1 + random.uniform(-jitter, jitter)
        time.sleep(max(0.0, sleep_for))
        result = attempt()
        delay = min(delay * 2, max_delay)
    return result
