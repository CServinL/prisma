"""Unit tests for Supervisor.monitor_loop's crash-loop give-up logic."""
import threading
import time
from unittest.mock import MagicMock

from prisma.server.supervisor import Supervisor


class _FakeEvent:
    """Stands in for threading.Event's is_set/set/wait, but wait() returns
    instantly instead of really sleeping -- lets monitor_loop's backoff
    waits run at test speed."""

    def __init__(self) -> None:
        self._flag = False

    def is_set(self) -> bool:
        return self._flag

    def set(self) -> None:
        self._flag = True

    def wait(self, timeout: float | None = None) -> bool:
        return self._flag


class _FakeWorker:
    def __init__(self, uptime: float) -> None:
        self._uptime = uptime
        self.restart_calls = 0

    def is_alive(self) -> bool:
        return False

    def uptime(self) -> float:
        return self._uptime

    def restart(self) -> None:
        self.restart_calls += 1


def _run_until_given_up(sup: Supervisor, name: str, timeout: float = 2.0) -> None:
    sup._stop_event = _FakeEvent()
    t = threading.Thread(target=sup.monitor_loop, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while name not in sup._given_up and time.monotonic() < deadline:
        time.sleep(0.005)
    sup._stop_event.set()
    t.join(timeout=1.0)


def test_monitor_loop_gives_up_after_repeated_fast_deaths():
    worker = _FakeWorker(uptime=0.5)  # always well under _FAST_DEATH_THRESHOLD
    sup = Supervisor({"api": worker}, MagicMock())

    _run_until_given_up(sup, "api")

    assert "api" in sup._given_up
    assert worker.restart_calls == Supervisor._MAX_FAST_DEATHS - 1


def test_monitor_loop_does_not_give_up_on_slow_deaths():
    # Dies well after the fast-death threshold each time -- a real
    # transient crash, not a doomed-to-repeat config error.
    worker = _FakeWorker(uptime=Supervisor._FAST_DEATH_THRESHOLD + 1.0)
    sup = Supervisor({"api": worker}, MagicMock())
    sup._stop_event = _FakeEvent()

    t = threading.Thread(target=sup.monitor_loop, daemon=True)
    t.start()
    time.sleep(0.2)
    sup._stop_event.set()
    t.join(timeout=1.0)

    assert "api" not in sup._given_up
    assert worker.restart_calls >= Supervisor._MAX_FAST_DEATHS
