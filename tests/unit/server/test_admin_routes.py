"""Unit tests for prisma.server.admin_routes — built in isolation (a bare
FastAPI app wrapping just build_admin_router + a MagicMock indexer), not
the full prisma.server.app singleton, same approach as
test_sync_routes.py/test_notes_routes.py. Previously these 6 routes had
zero dedicated test coverage anywhere.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.admin_routes import build_admin_router


@pytest.fixture
def indexer() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(indexer) -> TestClient:
    app = FastAPI()
    app.include_router(build_admin_router(get_indexer=lambda: indexer))
    return TestClient(app)


def test_taint_marks_index_stale(client, indexer):
    r = client.post("/admin/kg/taint")
    assert r.status_code == 200
    assert r.json() == {"status": "stale"}
    indexer.mark_stale.assert_called_once_with()


def test_drop_drops_index(client, indexer):
    r = client.post("/admin/kg/drop")
    assert r.status_code == 200
    assert r.json() == {"status": "dropped"}
    indexer.drop_index.assert_called_once()


def test_list_dead_letters(client, indexer):
    indexer.list_dead_letters.return_value = []
    r = client.get("/admin/kg/dead-letters")
    assert r.status_code == 200
    assert r.json() == []


def test_clear_dead_letters_returns_removed_count(client, indexer):
    indexer.clear_dead_letters.return_value = 3
    r = client.delete("/admin/kg/dead-letters")
    assert r.status_code == 200
    assert r.json() == {"removed": 3}


def test_entities_for_file(client, indexer):
    indexer.entities_for_file.return_value = {"entities": [], "edges": [], "extracted_by": None}
    r = client.get("/admin/kg/entities", params={"path": "notes/foo.md"})
    assert r.status_code == 200
    indexer.entities_for_file.assert_called_once_with("notes/foo.md")


def test_entities_requires_path_param(client):
    r = client.get("/admin/kg/entities")
    assert r.status_code == 422


def test_search_passes_query_and_top_k(client, indexer):
    indexer.search.return_value = []
    r = client.get("/admin/kg/search", params={"q": "neural networks", "top_k": 5})
    assert r.status_code == 200
    indexer.search.assert_called_once_with("neural networks", top_k=5)


def test_search_requires_nonempty_q(client):
    r = client.get("/admin/kg/search", params={"q": ""})
    assert r.status_code == 422
