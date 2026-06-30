"""Logic tests for the UI dev watcher (_src_hash, _ui_watcher, /ui/dev/version)."""
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── _src_hash ─────────────────────────────────────────────────────────────────

def test_src_hash_empty_dir(tmp_path):
    """Hash of an empty directory is stable across two calls."""
    from prisma.server.app import _src_hash
    with patch("prisma.server.app._ui_src", tmp_path):
        h1 = _src_hash()
        h2 = _src_hash()
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 32  # MD5 hex


def test_src_hash_changes_on_file_write(tmp_path):
    """Hash changes when a file's mtime_ns changes."""
    from prisma.server.app import _src_hash
    f = tmp_path / "Component.svelte"
    f.write_text("export let x = 1;")
    with patch("prisma.server.app._ui_src", tmp_path):
        h1 = _src_hash()
        time.sleep(0.01)  # ensure mtime_ns advances
        f.write_text("export let x = 2;")
        h2 = _src_hash()
    assert h1 != h2


def test_src_hash_stable_without_changes(tmp_path):
    """Hash is identical across multiple reads when nothing changes."""
    from prisma.server.app import _src_hash
    (tmp_path / "a.svelte").write_text("a")
    (tmp_path / "b.svelte").write_text("b")
    with patch("prisma.server.app._ui_src", tmp_path):
        hashes = [_src_hash() for _ in range(5)]
    assert len(set(hashes)) == 1


def test_src_hash_new_file_detected(tmp_path):
    """Hash changes when a new file is added."""
    from prisma.server.app import _src_hash
    (tmp_path / "existing.svelte").write_text("x")
    with patch("prisma.server.app._ui_src", tmp_path):
        h1 = _src_hash()
        (tmp_path / "new.svelte").write_text("y")
        h2 = _src_hash()
    assert h1 != h2


# ── _ui_watcher state machine ─────────────────────────────────────────────────

def test_watcher_increments_version_on_change(tmp_path):
    """Watcher increments version and clears building flag after a detected change.

    Drives the watcher loop directly: _src_hash returns two different values
    (simulating a file change), then raises StopIteration on the debounce sleep
    so the loop exits after one iteration.
    """
    import prisma.server.app as app_module

    original_state = app_module._ui_dev_state.copy()
    try:
        app_module._ui_dev_state = {"version": 0, "building": False}

        build_called = threading.Event()

        def fake_run(cmd, **kwargs):
            build_called.set()
            return MagicMock(returncode=0)

        hash_calls = [0]

        def hash_sequence():
            hash_calls[0] += 1
            # First call: initial snapshot (loop start)
            # Second call: poll — return a different value to signal change
            # Third call: after debounce — still different, so build triggers
            return "hash-A" if hash_calls[0] == 1 else "hash-B"

        sleep_calls = [0]

        def controlled_sleep(s):
            sleep_calls[0] += 1
            if sleep_calls[0] == 2:
                # Second sleep is the debounce; after this the loop calls _src_hash
                # then runs build — stop after build by raising on next sleep
                pass
            elif sleep_calls[0] >= 3:
                raise StopIteration

        with patch("prisma.server.app._src_hash", side_effect=hash_sequence), \
             patch("prisma.server.app._subprocess.run", side_effect=fake_run), \
             patch("prisma.server.app.time.sleep", side_effect=controlled_sleep):
            try:
                app_module._ui_watcher()
            except StopIteration:
                pass

        assert build_called.is_set()
        assert app_module._ui_dev_state["version"] == 1
        assert app_module._ui_dev_state["building"] is False

    finally:
        app_module._ui_dev_state = original_state


def test_watcher_no_build_when_unchanged(tmp_path):
    """Watcher does not call build if the hash doesn't change."""
    import prisma.server.app as app_module

    original_src = app_module._ui_src
    original_state = app_module._ui_dev_state.copy()

    try:
        app_module._ui_src = tmp_path
        app_module._ui_dev_state = {"version": 0, "building": False}
        (tmp_path / "page.svelte").write_text("stable")

        call_count = [0]

        def counting_sleep(s):
            call_count[0] += 1
            if call_count[0] >= 3:
                raise StopIteration

        with patch("prisma.server.app._subprocess.run") as mock_build, \
             patch("time.sleep", side_effect=counting_sleep):
            try:
                app_module._ui_watcher()
            except StopIteration:
                pass

        mock_build.assert_not_called()
        assert app_module._ui_dev_state["version"] == 0

    finally:
        app_module._ui_src = original_src
        app_module._ui_dev_state = original_state


# ── /ui/dev/version endpoint ──────────────────────────────────────────────────

def test_dev_version_endpoint_initial():
    """Endpoint returns version=0, building=False at startup."""
    from fastapi.testclient import TestClient
    import prisma.server.app as app_module

    original_state = app_module._ui_dev_state.copy()
    try:
        app_module._ui_dev_state = {"version": 0, "building": False}
        client = TestClient(app_module.app, raise_server_exceptions=True)
        r = client.get("/ui/dev/version")
        assert r.status_code == 200
        assert r.json() == {"version": 0, "building": False}
    finally:
        app_module._ui_dev_state = original_state


def test_dev_version_endpoint_reflects_state():
    """Endpoint reflects current version and building flag."""
    from fastapi.testclient import TestClient
    import prisma.server.app as app_module

    original_state = app_module._ui_dev_state.copy()
    try:
        app_module._ui_dev_state = {"version": 3, "building": True}
        client = TestClient(app_module.app, raise_server_exceptions=True)
        r = client.get("/ui/dev/version")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == 3
        assert data["building"] is True
    finally:
        app_module._ui_dev_state = original_state
