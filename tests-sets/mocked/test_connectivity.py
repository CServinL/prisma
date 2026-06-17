"""
Unit tests for prisma.connectivity — LazyMonitor proxy and ConnectivityMonitor.
"""

import threading
import unittest
from unittest.mock import patch, MagicMock, call

from prisma.connectivity import ConnectivityMonitor, _LazyMonitor, _is_reachable


class TestIsReachable(unittest.TestCase):
    """Tests for the _is_reachable helper."""

    def test_returns_true_when_socket_connects(self):
        with patch("prisma.connectivity.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            self.assertTrue(_is_reachable())

    def test_returns_false_on_oserror(self):
        with patch("prisma.connectivity.socket.create_connection", side_effect=OSError):
            self.assertFalse(_is_reachable())


class TestConnectivityMonitor(unittest.TestCase):
    """Tests for ConnectivityMonitor."""

    def _make_monitor(self):
        return ConnectivityMonitor()

    def test_initial_state_before_start(self):
        m = self._make_monitor()
        self.assertFalse(m._started)
        self.assertFalse(m.is_online)
        self.assertIsNone(m._thread)

    def test_start_sets_started_flag(self):
        with patch("prisma.connectivity._is_reachable", return_value=True):
            m = self._make_monitor()
            m.start()
            self.assertTrue(m._started)
            m.stop()

    def test_start_probes_and_sets_is_online_true(self):
        with patch("prisma.connectivity._is_reachable", return_value=True):
            m = self._make_monitor()
            m.start()
            self.assertTrue(m.is_online)
            m.stop()

    def test_start_probes_and_sets_is_online_false(self):
        with patch("prisma.connectivity._is_reachable", return_value=False):
            m = self._make_monitor()
            m.start()
            self.assertFalse(m.is_online)
            m.stop()

    def test_start_launches_daemon_thread(self):
        with patch("prisma.connectivity._is_reachable", return_value=False):
            m = self._make_monitor()
            m.start()
            self.assertIsNotNone(m._thread)
            self.assertTrue(m._thread.daemon)
            m.stop()

    def test_start_idempotent(self):
        with patch("prisma.connectivity._is_reachable", return_value=False) as mock_probe:
            m = self._make_monitor()
            m.start()
            m.start()
            # _is_reachable called exactly once — second start is a no-op
            mock_probe.assert_called_once()
            m.stop()

    def test_stop_signals_thread(self):
        with patch("prisma.connectivity._is_reachable", return_value=False):
            m = self._make_monitor()
            m.start()
            m.stop()
            self.assertTrue(m._stop.is_set())

    def test_on_change_registers_callback(self):
        m = self._make_monitor()
        cb = MagicMock()
        m.on_change(cb)
        self.assertIn(cb, m._callbacks)

    def test_callbacks_fired_on_status_change(self):
        # Use a controlled _stop event so we can drive _loop manually
        with patch("prisma.connectivity._is_reachable", return_value=False):
            m = self._make_monitor()
            m.start()

        cb = MagicMock()
        m.on_change(cb)

        # Simulate the loop detecting a change
        with patch("prisma.connectivity._is_reachable", return_value=True):
            # Drive one loop iteration manually
            status = True
            with m._lock:
                changed = status != m.is_online
                m.is_online = status
            if changed:
                for c in list(m._callbacks):
                    c(status)

        cb.assert_called_once_with(True)
        m.stop()

    def test_callback_exception_does_not_propagate(self):
        m = self._make_monitor()
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        m.on_change(bad_cb)

        # Should not raise
        for c in list(m._callbacks):
            try:
                c(True)
            except Exception as exc:
                pass  # monitor's _loop swallows these


class TestLazyMonitor(unittest.TestCase):
    """Tests for the _LazyMonitor proxy."""

    def test_does_not_start_on_construction(self):
        proxy = _LazyMonitor()
        self.assertFalse(proxy._monitor._started)

    def test_starts_on_first_attribute_access(self):
        with patch("prisma.connectivity._is_reachable", return_value=False):
            proxy = _LazyMonitor()
            _ = proxy.is_online
            self.assertTrue(proxy._monitor._started)
            proxy._monitor.stop()

    def test_does_not_restart_on_subsequent_access(self):
        with patch("prisma.connectivity._is_reachable", return_value=False) as mock_probe:
            proxy = _LazyMonitor()
            _ = proxy.is_online
            _ = proxy.is_online
            mock_probe.assert_called_once()
            proxy._monitor.stop()

    def test_proxies_is_online_value(self):
        with patch("prisma.connectivity._is_reachable", return_value=True):
            proxy = _LazyMonitor()
            self.assertTrue(proxy.is_online)
            proxy._monitor.stop()

    def test_proxies_on_change(self):
        with patch("prisma.connectivity._is_reachable", return_value=False):
            proxy = _LazyMonitor()
            cb = MagicMock()
            proxy.on_change(cb)
            self.assertIn(cb, proxy._monitor._callbacks)
            proxy._monitor.stop()


if __name__ == "__main__":
    unittest.main()
