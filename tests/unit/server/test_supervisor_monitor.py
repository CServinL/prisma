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
        # monitor_loop() coordinates with a manual restart via this lock
        # (see Worker._restart_lock) -- a real Lock so acquire(blocking=False)
        # behaves like the genuine article.
        self._restart_lock = threading.Lock()

    def is_alive(self) -> bool:
        return False

    def uptime(self) -> float:
        return self._uptime

    def restart(self) -> None:
        self.restart_calls += 1

    def _do_restart(self) -> None:
        # monitor_loop() calls this directly (already holding _restart_lock),
        # not restart() -- see Worker._do_restart's docstring.
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


def test_monitor_loop_does_not_pile_on_a_restart_already_in_progress():
    # A held lock simulates a manual restart's stop()-to-start() window,
    # where the worker looks not-alive without having actually crashed.
    worker = _FakeWorker(uptime=0.5)
    worker._restart_lock.acquire()
    sup = Supervisor({"api": worker}, MagicMock())
    sup._stop_event = _FakeEvent()

    t = threading.Thread(target=sup.monitor_loop, daemon=True)
    t.start()
    time.sleep(0.2)
    sup._stop_event.set()
    t.join(timeout=1.0)

    assert worker.restart_calls == 0
    assert "api" not in sup._given_up


def test_monitor_loop_releases_the_lock_during_its_backoff_wait():
    # Otherwise a manual restart blocks for the whole backoff delay.
    class _CheckingEvent(_FakeEvent):
        def __init__(self) -> None:
            super().__init__()
            self.acquired_during_wait: bool | None = None

        def wait(self, timeout: float | None = None) -> bool:
            # Skip the flat _POLL_INTERVAL wait -- only the backoff wait matters here.
            if timeout is not None and timeout != Supervisor._POLL_INTERVAL:
                self.acquired_during_wait = worker._restart_lock.acquire(blocking=False)
                if self.acquired_during_wait:
                    worker._restart_lock.release()
            return self._flag

    worker = _FakeWorker(uptime=0.5)
    sup = Supervisor({"api": worker}, MagicMock())
    event = _CheckingEvent()
    sup._stop_event = event

    t = threading.Thread(target=sup.monitor_loop, daemon=True)
    t.start()
    time.sleep(0.2)
    sup._stop_event.set()
    t.join(timeout=1.0)

    assert event.acquired_during_wait is True


class _RecoverableFakeWorker(_FakeWorker):
    """Can be flipped from crash-looping to healthy. Stays not-alive for
    two more checks after that -- monitor_loop calls is_alive() twice per
    cycle, and one reading alone gets absorbed without ever reaching the
    fast_deaths-increment path."""

    def __init__(self, uptime: float) -> None:
        super().__init__(uptime)
        self.healthy = False
        self._not_alive_checks_remaining_after_healthy = 0

    def is_alive(self) -> bool:
        if self.healthy and self._not_alive_checks_remaining_after_healthy > 0:
            self._not_alive_checks_remaining_after_healthy -= 1
            return False
        return self.healthy


def test_manual_restart_reset_prevents_immediate_re_give_up():
    worker = _RecoverableFakeWorker(uptime=0.5)
    sup = Supervisor({"api": worker}, MagicMock())
    _run_until_given_up(sup, "api")
    assert "api" in sup._given_up
    assert sup._fast_deaths["api"] >= Supervisor._MAX_FAST_DEATHS

    # Mirrors supervisor.py's do_POST restart handler.
    worker.healthy = True
    worker._not_alive_checks_remaining_after_healthy = 2
    sup._given_up.discard("api")
    sup._fast_deaths["api"] = 0
    sup._backoff["api"] = 1.0

    sup._stop_event = _FakeEvent()
    t = threading.Thread(target=sup.monitor_loop, daemon=True)
    t.start()
    time.sleep(0.2)
    sup._stop_event.set()
    t.join(timeout=1.0)

    assert "api" not in sup._given_up
