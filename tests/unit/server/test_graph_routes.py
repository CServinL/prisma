"""Unit tests for prisma.server.graph_routes — the public /graph/*
capability surface. Built in isolation over a MagicMock client, same
approach as test_admin_routes.py.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.graph_routes import build_graph_router
from prisma.storage.models.kg_models import (
    AuthorSummary,
    EntityInfo,
    ExpandNodeResponse,
    SurprisingConnection,
    TimelineEntry,
    TopEntity,
    VaultHealthResponse,
)
from prisma.storage.models.kg_models import OrphanEntity


@pytest.fixture
def client_stub() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(client_stub) -> TestClient:
    app = FastAPI()
    app.include_router(build_graph_router(get_client=lambda: client_stub))
    return TestClient(app)


def test_expand_node_forwards_id(client, client_stub):
    client_stub.expand_node.return_value = ExpandNodeResponse(
        entities=[EntityInfo(id="n1", label="N1")], edges=[],
    )
    r = client.get("/graph/expand_node", params={"id": "center"})
    assert r.status_code == 200
    assert r.json()["entities"][0]["id"] == "n1"
    client_stub.expand_node.assert_called_once_with("center")


def test_expand_node_requires_id(client):
    assert client.get("/graph/expand_node").status_code == 422


def test_god_nodes_passes_limit(client, client_stub):
    client_stub.god_nodes.return_value = [TopEntity(id="h", label="H", degree=4)]
    r = client.get("/graph/god_nodes", params={"limit": 5})
    assert r.status_code == 200
    client_stub.god_nodes.assert_called_once_with(limit=5)


def test_god_nodes_rejects_out_of_range_limit(client):
    assert client.get("/graph/god_nodes", params={"limit": 0}).status_code == 422
    assert client.get("/graph/god_nodes", params={"limit": 999}).status_code == 422


def test_surprising_connections_passes_limit(client, client_stub):
    client_stub.surprising_connections.return_value = [
        SurprisingConnection(entity_a="a", entity_b="c", bridge="b", relation_a="cites", relation_b="extends", score=0.8),
    ]
    r = client.get("/graph/surprising_connections", params={"limit": 5})
    assert r.status_code == 200
    assert r.json()[0]["bridge"] == "b"
    client_stub.surprising_connections.assert_called_once_with(limit=5)


def test_surprising_connections_rejects_out_of_range_limit(client):
    assert client.get("/graph/surprising_connections", params={"limit": 0}).status_code == 422
    assert client.get("/graph/surprising_connections", params={"limit": 999}).status_code == 422


def test_authors_default_limit(client, client_stub):
    client_stub.authors.return_value = [AuthorSummary(author="Ada", file_count=2)]
    r = client.get("/graph/authors")
    assert r.status_code == 200
    client_stub.authors.assert_called_once_with(limit=100)


def test_vault_health(client, client_stub):
    client_stub.vault_health.return_value = VaultHealthResponse(
        orphans=[OrphanEntity(id="o1", label="O1")], orphan_count=1,
    )
    r = client.get("/graph/vault_health")
    assert r.status_code == 200
    assert r.json()["orphan_count"] == 1


def test_timeline_forwards_query(client, client_stub):
    client_stub.timeline.return_value = [
        TimelineEntry(id="e1", label="Transformers", year=2017),
    ]
    r = client.get("/graph/timeline", params={"q": "transformers"})
    assert r.status_code == 200
    assert r.json()[0]["year"] == 2017
    client_stub.timeline.assert_called_once_with("transformers")


def test_timeline_requires_nonempty_q(client):
    assert client.get("/graph/timeline", params={"q": ""}).status_code == 422
