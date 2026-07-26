"""Unit tests for prisma.server.sync_routes — built in isolation (a bare
FastAPI app wrapping just build_sync_router + a tmp_path VaultService), not
the full prisma.server.app singleton, so these don't depend on auth/CORS/the
real vault_root and stay independently testable per the vault-sync plan.
"""
import math
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.sync_routes import build_sync_router
from prisma.services.vault import VaultService


class _Recorder:
    """Fake broadcast_fn/mark_stale_fn/baseline callbacks that just record calls."""

    def __init__(self):
        self.broadcasts = []
        self.mark_stale_calls = 0
        self.mark_stale_paths = []
        self.baseline_updates = []  # (client_id, path, hash, mtime)
        self.baseline_clears = []  # (client_id, path)

    def broadcast(self, event, exclude_client_id=None):
        self.broadcasts.append((event, exclude_client_id))

    def mark_stale(self, path):
        self.mark_stale_calls += 1
        self.mark_stale_paths.append(path)

    def update_baseline(self, client_id, path, content_hash, mtime):
        self.baseline_updates.append((client_id, path, content_hash, mtime))

    def clear_baseline(self, client_id, path):
        self.baseline_clears.append((client_id, path))


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def client(vault, recorder) -> TestClient:
    app = FastAPI()
    app.include_router(build_sync_router(
        get_vault=lambda: vault,
        broadcast_fn=recorder.broadcast,
        mark_stale_fn=recorder.mark_stale,
        update_baseline_fn=recorder.update_baseline,
        clear_baseline_fn=recorder.clear_baseline,
    ))
    return TestClient(app)


def test_manifest_empty_vault(client):
    r = client.get("/sync/manifest")
    assert r.status_code == 200
    assert r.json() == []


def test_put_new_file_creates_and_broadcasts(client, vault, recorder):
    r = client.put("/sync/file", json={"path": "notes/a.md", "body": "hello", "expected_mtime": None})
    assert r.status_code == 200
    assert r.json()["body"] == "hello"
    assert vault.read_by_path("notes/a.md")[0] == "hello"
    assert recorder.mark_stale_calls == 1
    assert recorder.mark_stale_paths == ["notes/a.md"]
    assert len(recorder.broadcasts) == 1
    event, exclude = recorder.broadcasts[0]
    assert event == {"type": "vault_change", "action": "sync_write", "path": "notes/a.md"}
    assert exclude is None  # no X-Sync-Client-Id header sent


def test_put_echoes_exclude_client_id_from_header(client, recorder):
    r = client.put(
        "/sync/file",
        json={"path": "notes/a.md", "body": "hello", "expected_mtime": None},
        headers={"X-Sync-Client-Id": "desktop-123"},
    )
    assert r.status_code == 200
    _, exclude = recorder.broadcasts[0]
    assert exclude == "desktop-123"


def test_put_with_client_id_updates_baseline(client, recorder):
    r = client.put(
        "/sync/file",
        json={"path": "notes/a.md", "body": "hello", "expected_mtime": None},
        headers={"X-Sync-Client-Id": "desktop-123"},
    )
    mtime = r.json()["mtime"]
    import hashlib
    assert recorder.baseline_updates == [
        ("desktop-123", "notes/a.md", hashlib.sha256(b"hello").hexdigest(), mtime)
    ]


def test_put_without_client_id_does_not_touch_baseline(client, recorder):
    client.put("/sync/file", json={"path": "notes/a.md", "body": "hello", "expected_mtime": None})
    assert recorder.baseline_updates == []


def test_delete_with_client_id_clears_baseline(client, recorder, vault):
    vault.write_by_path("notes/a.md", "content")
    client.delete("/sync/file", params={"path": "notes/a.md"}, headers={"X-Sync-Client-Id": "desktop-123"})
    assert recorder.baseline_clears == [("desktop-123", "notes/a.md")]


def test_get_file_roundtrip(client, vault):
    vault.write_by_path("notes/a.md", "content")
    r = client.get("/sync/file", params={"path": "notes/a.md"})
    assert r.status_code == 200
    assert r.json()["body"] == "content"


def test_get_missing_file_404(client):
    r = client.get("/sync/file", params={"path": "notes/missing.md"})
    assert r.status_code == 404


def test_put_conflicting_mtime_returns_409_with_server_state(client, vault):
    vault.write_by_path("notes/a.md", "server version")
    r = client.put("/sync/file", json={"path": "notes/a.md", "body": "client version", "expected_mtime": 1.0})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["body"] == "server version"
    # server-side content must be untouched by the rejected write
    assert vault.read_by_path("notes/a.md")[0] == "server version"


def test_put_new_but_server_already_has_file_conflicts(client, vault):
    vault.write_by_path("notes/a.md", "server version")
    r = client.put("/sync/file", json={"path": "notes/a.md", "body": "client version", "expected_mtime": None})
    assert r.status_code == 409


def test_put_matching_expected_mtime_succeeds(client, vault):
    mtime = vault.write_by_path("notes/a.md", "v1")
    r = client.put("/sync/file", json={"path": "notes/a.md", "body": "v2", "expected_mtime": mtime})
    assert r.status_code == 200
    assert vault.read_by_path("notes/a.md")[0] == "v2"


def test_put_one_ulp_off_expected_mtime_still_succeeds(client, vault):
    # Regression test for a real 2026-07-25 bug: a Unix timestamp at today's
    # magnitude (~1.78e9) leaves float64 only ~238ns of resolution, so a
    # value round-tripped through JSON across languages (Python -> Rust ->
    # Python) can land one ULP off from the server's freshly-read mtime.
    # Exact equality treated this as a real conflict forever, with no way
    # for the client to ever converge -- confirmed live: expected_mtime one
    # ULP away from the true mtime 409'd endlessly, in an infinite loop the
    # client could never resolve (see sync_routes.py's _MTIME_TOLERANCE_SECONDS).
    mtime = vault.write_by_path("notes/a.md", "v1")
    off_by_one_ulp = math.nextafter(mtime, math.inf)
    assert off_by_one_ulp != mtime  # sanity check this is a real distinct float
    r = client.put("/sync/file", json={"path": "notes/a.md", "body": "v2", "expected_mtime": off_by_one_ulp})
    assert r.status_code == 200
    assert vault.read_by_path("notes/a.md")[0] == "v2"


def test_delete_file_removes_and_broadcasts(client, vault, recorder):
    vault.write_by_path("notes/a.md", "content")
    r = client.delete("/sync/file", params={"path": "notes/a.md"})
    assert r.status_code == 200
    assert vault.read_by_path("notes/a.md") is None
    assert recorder.mark_stale_calls == 1
    event, _ = recorder.broadcasts[0]
    assert event["action"] == "sync_delete"


def test_put_path_traversal_rejected(client):
    r = client.put("/sync/file", json={"path": "../outside.md", "body": "x", "expected_mtime": None})
    assert r.status_code == 403


def test_manifest_lists_written_files(client, vault):
    vault.write_by_path("notes/a.md", "aa")
    vault.write_by_path("notes/b.md", "b")
    r = client.get("/sync/manifest")
    paths = {entry["path"] for entry in r.json()}
    assert paths == {"notes/a.md", "notes/b.md"}
