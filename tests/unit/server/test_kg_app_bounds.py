"""The kg worker binds to a host (supervisor.py) and is directly reachable,
so its own routes must validate inputs -- the /graph public router is not
the only line of defence."""
from fastapi.testclient import TestClient

from prisma.server import kg_app
from prisma.services import kg_queries
from prisma.services.knowledge_graph_service import TOP_ENTITIES_CACHE_SIZE

client = TestClient(kg_app.app)


def test_expand_node_rejects_oversized_limit_and_id():
    assert client.get("/expand_node", params={"id": "x", "limit": kg_queries.EXPAND_MAX + 1}).status_code == 422
    assert client.get("/expand_node", params={"id": "x" * 600}).status_code == 422


def test_timeline_rejects_oversized_limit_and_query():
    assert client.get("/timeline", params={"q": "x", "limit": kg_queries.TIMELINE_MAX + 1}).status_code == 422
    assert client.get("/timeline", params={"q": "x" * 600}).status_code == 422


def test_required_free_text_params_reject_empty_string():
    # Same floor the public /graph/* router enforces -- the worker binds to a
    # host and is reachable directly, so an empty ?id=/?q=/?rel= is a client
    # error here too, not just there.
    assert client.get("/expand_node", params={"id": ""}).status_code == 422
    assert client.get("/timeline", params={"q": ""}).status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422
    assert client.get("/ranked_nodes", params={"q": ""}).status_code == 422
    assert client.get("/query", params={"q": ""}).status_code == 422
    assert client.get("/entities_for_file", params={"rel": ""}).status_code == 422


def test_aggregate_routes_reject_oversized_limit():
    assert client.get("/god_nodes", params={"limit": kg_queries.GOD_NODES_MAX + 1}).status_code == 422
    assert client.get("/authors", params={"limit": kg_queries.AUTHORS_MAX + 1}).status_code == 422
    assert client.get("/vault_health", params={"limit": kg_queries.VAULT_HEALTH_MAX + 1}).status_code == 422
    assert client.get("/surprising_connections", params={"limit": kg_queries.SURPRISING_CONNECTIONS_MAX + 1}).status_code == 422
    assert client.get("/suggest_questions", params={"limit": kg_queries.SUGGEST_QUESTIONS_MAX + 1}).status_code == 422


def test_graph_relevance_rejects_oversized_list_and_string():
    # Directly reachable on the kg worker, same as every route above -- an
    # unbounded batch or an unbounded per-string length is a real cost
    # (one full label-list scan per text), not just a shape concern.
    oversized_list = {"texts": ["x"] * (kg_queries.GRAPH_RELEVANCE_MAX_TEXTS + 1)}
    assert client.post("/graph_relevance", json=oversized_list).status_code == 422
    oversized_string = {"texts": ["x" * (kg_queries.GRAPH_RELEVANCE_MAX_TEXT_LENGTH + 1)]}
    assert client.post("/graph_relevance", json=oversized_string).status_code == 422


def test_graph_relevance_accepts_a_within_bounds_request():
    r = client.post("/graph_relevance", json={"texts": ["hello world"]})
    assert r.status_code == 200
    assert r.json() == [{"score": 0, "matched_entities": []}]


def test_top_entities_limit_is_bound_by_the_cache_size():
    # The cache holds exactly TOP_ENTITIES_CACHE_SIZE rows, so asking for
    # more is a client error rather than a silently-clamped request.
    assert client.get("/top_entities", params={"limit": TOP_ENTITIES_CACHE_SIZE + 1}).status_code == 422
