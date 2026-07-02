"""Unit tests for prisma.services.backoff — the generic retry/backoff helper."""
from unittest.mock import patch

from prisma.services import backoff


def test_returns_immediately_on_first_success():
    calls = []

    def attempt():
        calls.append(1)
        return "ok"

    with patch("prisma.services.backoff.time.sleep") as mock_sleep:
        result = backoff.retry_with_backoff(attempt, is_success=lambda r: r == "ok")

    assert result == "ok"
    assert len(calls) == 1
    assert not mock_sleep.called


def test_retries_until_success():
    responses = iter(["busy", "busy", "ok"])

    def attempt():
        return next(responses)

    with patch("prisma.services.backoff.time.sleep"):
        result = backoff.retry_with_backoff(attempt, is_success=lambda r: r == "ok")

    assert result == "ok"


def test_gives_up_after_max_wait_and_returns_last_result():
    call_count = 0

    def attempt():
        nonlocal call_count
        call_count += 1
        return "busy"

    with patch("prisma.services.backoff.time.sleep"):
        result = backoff.retry_with_backoff(
            attempt, is_success=lambda r: r == "ok", max_wait=0.01,
        )

    assert result == "busy"
    assert call_count >= 1


def test_delay_doubles_up_to_max_delay():
    responses = iter(["busy"] * 5 + ["ok"])
    delays = []

    def attempt():
        return next(responses)

    def fake_sleep(seconds):
        delays.append(seconds)

    with patch("prisma.services.backoff.time.sleep", side_effect=fake_sleep):
        backoff.retry_with_backoff(
            attempt, is_success=lambda r: r == "ok",
            max_wait=100.0, base_delay=1.0, max_delay=4.0, jitter=0.0,
        )

    assert delays[0] == 1.0
    assert delays[1] == 2.0
    assert delays[2] == 4.0
    assert delays[3] == 4.0  # capped at max_delay
