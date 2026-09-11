"""The kg worker binds to a host (supervisor.py) and is directly reachable,
so its own routes must validate inputs -- the /graph public router is not
the only line of defence."""
from fastapi.testclient import TestClient

from prisma.server import kg_app
from prisma.services import kg_queries

client = TestClient(kg_app.app)


def test_expand_node_rejects_oversized_limit_and_id():
    assert client.get("/expand_node", params={"id": "x", "limit": kg_queries.EXPAND_MAX + 1}).status_code == 422
    assert client.get("/expand_node", params={"id": "x" * 600}).status_code == 422


def test_timeline_rejects_oversized_limit_and_query():
    assert client.get("/timeline", params={"q": "x", "limit": kg_queries.TIMELINE_MAX + 1}).status_code == 422
    assert client.get("/timeline", params={"q": "x" * 600}).status_code == 422


def test_aggregate_routes_reject_oversized_limit():
    assert client.get("/god_nodes", params={"limit": kg_queries.GOD_NODES_MAX + 1}).status_code == 422
    assert client.get("/authors", params={"limit": kg_queries.AUTHORS_MAX + 1}).status_code == 422
    assert client.get("/vault_health", params={"limit": kg_queries.VAULT_HEALTH_MAX + 1}).status_code == 422
    assert client.get("/surprising_connections", params={"limit": kg_queries.SURPRISING_CONNECTIONS_MAX + 1}).status_code == 422
