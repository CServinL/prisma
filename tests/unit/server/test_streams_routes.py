"""Unit tests for prisma.server.streams_routes — built in isolation (a bare
FastAPI app wrapping just build_streams_router + a tmp_path VaultService),
not the full prisma.server.app singleton, same approach as
test_sync_routes.py/test_notes_routes.py.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.streams_routes import build_streams_router
from prisma.services.vault import VaultService


class _Recorder:
    def __init__(self):
        self.broadcasts = []

    def broadcast(self, event, exclude_client_id=None):
        self.broadcasts.append((event, exclude_client_id))


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def zotero() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(vault, zotero, recorder) -> TestClient:
    app = FastAPI()
    app.include_router(build_streams_router(
        get_vault=lambda: vault,
        get_zotero=lambda: zotero,
        broadcast_fn=recorder.broadcast,
    ))
    return TestClient(app)


def test_list_streams_empty(client):
    r = client.get("/streams")
    assert r.status_code == 200
    assert r.json() == []


def test_create_stream_then_list(client, vault):
    r = client.post("/streams", json={"title": "My Stream", "query": "deep learning"})
    assert r.status_code == 201
    data = r.json()
    assert data["slug"] == "my-stream"
    assert data["query"] == "deep learning"
    assert data["status"] == "active"

    r2 = client.get("/streams")
    assert len(r2.json()) == 1


def test_get_stream(client, vault):
    vault.create_stream(title="My Stream", query="q")
    r = client.get("/streams/my-stream")
    assert r.status_code == 200
    assert r.json()["slug"] == "my-stream"


def test_get_stream_not_found(client):
    r = client.get("/streams/does-not-exist")
    assert r.status_code == 404


def test_patch_stream_updates_fields(client, vault):
    vault.create_stream(title="My Stream", query="q")
    r = client.patch("/streams/my-stream", json={"status": "paused"})
    assert r.status_code == 200
    assert r.json()["status"] == "paused"


def test_patch_stream_not_found(client):
    r = client.patch("/streams/does-not-exist", json={"status": "paused"})
    assert r.status_code == 404


def test_delete_stream(client, vault):
    vault.create_stream(title="My Stream", query="q")
    r = client.delete("/streams/my-stream")
    assert r.status_code == 204
    assert client.get("/streams/my-stream").status_code == 404


def test_delete_stream_not_found(client):
    r = client.delete("/streams/does-not-exist")
    assert r.status_code == 404


def test_get_stream_view_renders_via_render_note(client, vault):
    vault.create_stream(title="My Stream", query="q")
    r = client.get("/streams/my-stream/view")
    assert r.status_code == 200
    assert r.json()["slug"] == "my-stream"


def test_run_stream_not_found(client):
    r = client.post("/streams/does-not-exist/run")
    assert r.status_code == 404


def test_run_stream_broadcasts_progress(client, vault, zotero, recorder):
    # Full run_stream() (via stream_runner) needs real SearchAgent/network --
    # out of scope for a router-isolation test. A future next_update with
    # force=False (this route's default) makes stream_runner short-circuit
    # before touching SearchAgent/ConfigLoader at all, letting this test
    # confirm the route wires through to run_stream_and_notify (broadcast
    # fires unconditionally, before that early-return check) without mocking
    # the network.
    from datetime import datetime, timedelta
    vault.create_stream(title="My Stream", query="q")
    vault.save_stream("my-stream", next_update=datetime.now() + timedelta(days=1))

    r = client.post("/streams/my-stream/run")
    assert r.status_code == 200
    assert "not due" in r.json()["errors"][0]
    assert recorder.broadcasts[0][0] == {"type": "stream_progress", "slug": "my-stream", "status": "running"}
