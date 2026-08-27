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
    # Confirmed live 2026-08-27: POST /supervisor/restart/{name} (Worker.
    # restart()) races with this loop -- a worker is not-alive for the whole
    # window between its stop() and start(), indistinguishable from a real
    # crash unless the two coordinate. Simulated here by holding the lock
    # for the loop's entire run, exactly as a manual restart's `with
    # self._restart_lock:` would.
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
    # Copilot review on PR #97: monitor_loop() used to hold _restart_lock
    # across the whole backoff sleep (up to Supervisor._MAX_BACKOFF=30s),
    # which would make a manual POST /supervisor/restart/{name} -- an
    # operator's own action -- block for the full delay even though it's
    # not the crash-detected restart at all. Checked here by having the
    # fake stop_event's wait() (monitor_loop's backoff sleep) itself try a
    # non-blocking acquire: it must succeed, proving the lock isn't held
    # during that window.
    class _CheckingEvent(_FakeEvent):
        def __init__(self) -> None:
            super().__init__()
            self.acquired_during_wait: bool | None = None

        def wait(self, timeout: float | None = None) -> bool:
            # Distinguish the backoff-delay wait (starts at 1.0, doubling)
            # from the outer poll-interval wait (a flat Supervisor.
            # _POLL_INTERVAL=2.0) so this specifically checks the window
            # Copilot's review was about, not just "eventually unlocked."
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
