"""Unit tests for the generic token-bucket RateLimiter -- no network."""

import threading
import time

import pytest

from prisma.services.rate_limiter import RateLimiter


def test_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        RateLimiter(requests_per_second=0)
    with pytest.raises(ValueError):
        RateLimiter(requests_per_second=-1)


def test_smooths_to_configured_rate():
    limiter = RateLimiter(requests_per_second=20)  # 1 token per 0.05s
    start = time.monotonic()
    for _ in range(5):
        assert limiter.acquire(timeout=1.0)
    elapsed = time.monotonic() - start
    # 5 tokens at 20/s: first is immediate, remaining 4 spaced 0.05s apart
    assert 0.15 <= elapsed <= 0.35


def test_timeout_denies_when_bucket_empty():
    limiter = RateLimiter(requests_per_second=1)
    assert limiter.acquire(timeout=0.1)  # first token free
    assert not limiter.acquire(timeout=0.05)  # next isn't due for ~1s


def test_daily_cap_denies_immediately_without_waiting():
    limiter = RateLimiter(requests_per_second=1000, daily_cap=2)
    assert limiter.acquire(timeout=0.5)
    assert limiter.acquire(timeout=0.5)
    start = time.monotonic()
    assert not limiter.acquire(timeout=5.0)
    # Denial must be immediate, not after waiting out most of the timeout --
    # waiting for a day-boundary reset is never the right behavior.
    assert time.monotonic() - start < 0.5


def test_daily_cap_not_double_consumed_by_retry_loop():
    """Regression test: a call that has to wait for the per-second
    interval (not the daily cap) must only consume one unit of daily
    budget for that one logical acquire(), even though it internally
    loops/retries while waiting."""
    limiter = RateLimiter(requests_per_second=50, daily_cap=3)
    for _ in range(3):
        assert limiter.acquire(timeout=1.0)
    assert not limiter.acquire(timeout=0.1)


def test_thread_safe_under_concurrent_callers():
    limiter = RateLimiter(requests_per_second=100)
    granted = []
    lock = threading.Lock()

    def worker():
        if limiter.acquire(timeout=3.0):
            with lock:
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) == 30
