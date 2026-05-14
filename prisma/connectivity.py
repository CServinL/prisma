"""
Connectivity monitor — polls internet availability and flips an internal flag.

Usage:
    from prisma.connectivity import monitor

    if monitor.is_online:
        ...  # safe to call Zotero API / arXiv / Semantic Scholar

The singleton is lazy-initialized on first access via `monitor`, so importing
this module does not start any thread or make any network call.
"""

import logging
import socket
import threading

logger = logging.getLogger(__name__)

_CHECK_HOST = "1.1.1.1"
_CHECK_PORT = 53
_CHECK_TIMEOUT = 3.0
_POLL_INTERVAL = 30  # seconds


def _is_reachable() -> bool:
    try:
        with socket.create_connection((_CHECK_HOST, _CHECK_PORT), timeout=_CHECK_TIMEOUT):
            return True
    except OSError:
        return False


class ConnectivityMonitor:
    """
    Polls internet reachability every POLL_INTERVAL seconds.
    Exposes `is_online: bool` and calls registered callbacks on status change.

    Call `start()` explicitly (or use the module-level `monitor` proxy which
    starts on first attribute access) to begin polling.
    """

    def __init__(self):
        self.is_online: bool = False
        self._lock = threading.Lock()
        self._callbacks: list = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self):
        """Perform initial probe and start background polling thread."""
        if self._started:
            return
        self._started = True
        self.is_online = _is_reachable()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="connectivity-monitor")
        self._thread.start()
        logger.info("ConnectivityMonitor started — initial status: %s", "online" if self.is_online else "offline")

    def _loop(self):
        while not self._stop.wait(_POLL_INTERVAL):
            status = _is_reachable()
            with self._lock:
                changed = status != self.is_online
                self.is_online = status
            if changed:
                label = "online" if status else "offline"
                logger.info("Connectivity changed → %s", label)
                for cb in list(self._callbacks):
                    try:
                        cb(status)
                    except Exception as exc:
                        logger.error("Connectivity callback error: %s", exc)

    def on_change(self, callback):
        """Register a callable(is_online: bool) invoked on every status change."""
        self._callbacks.append(callback)

    def stop(self):
        self._stop.set()


class _LazyMonitor:
    """Proxy that starts ConnectivityMonitor on first attribute access."""

    def __init__(self):
        self._monitor = ConnectivityMonitor()

    def __getattr__(self, name):
        if not self._monitor._started:
            self._monitor.start()
        return getattr(self._monitor, name)


# Module-level singleton — lazy, starts on first use
monitor = _LazyMonitor()
