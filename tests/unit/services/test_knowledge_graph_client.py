"""Unit tests for KnowledgeGraphClient — the thin HTTP client app.py uses to
reach the kg worker process (see prisma.server.kg_app)."""
from unittest.mock import MagicMock, patch

import requests

from prisma.services.knowledge_graph_client import KnowledgeGraphClient
from prisma.storage.models.search_models import GraphSearchResult


def _mock_response(data):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _kg_status_payload(**overrides):
    payload = {
        "state": "idle", "last_indexed": None, "last_error": None, "current_activity": None,
        "sync_total": 0, "sync_done": 0, "current_file": None,
        "current_file_chunks_done": 0, "current_file_chunks_total": 0,
        "chunk_avg_duration_ms": None, "chunk_duration_samples": 0,
        "chunk_avg_retries": None, "chunk_avg_size_tokens": None,
        "dropped_chunks_total": 0, "dropped_chunks_recent": [],
    }
    payload.update(overrides)
    return payload


def test_status_returns_json_on_success():
    client = KnowledgeGraphClient()
    payload = _kg_status_payload(state="idle", last_indexed="x", last_error=None)
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response(payload)):
        status = client.status()
    assert status.state == "idle"
    assert status.last_indexed == "x"
    assert status.last_error is None


def test_status_fails_open_when_kg_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        status = client.status()
    assert status.state == "stale"
    assert status.last_error is not None


def test_mark_stale_posts_to_kg():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post") as mock_post:
        client.mark_stale()
    assert mock_post.call_args[0][0].endswith("/mark_stale")
    assert mock_post.call_args.kwargs["params"] is None


def test_mark_stale_forwards_path_to_kg():
    # The kg process runs in its own worker (see this module's docstring),
    # so KnowledgeGraphService.mark_stale()'s path-relevance check (added
    # alongside prisma#42) needs the path to actually cross the HTTP
    # boundary, not just be accepted client-side and dropped.
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post") as mock_post:
        client.mark_stale("streams/my-topic.yaml")
    assert mock_post.call_args.kwargs["params"] == {"path": "streams/my-topic.yaml"}


def test_mark_stale_does_not_raise_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post", side_effect=requests.ConnectionError("down")):
        client.mark_stale()  # must not raise


def test_search_returns_empty_list_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        assert client.search("q") == []


def test_search_passes_params_and_returns_results():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response([{"source_file": "a.md", "score": 2.0}])) as mock_get:
        result = client.search("neural networks", top_k=5)
    assert [r.model_dump() for r in result] == [{"source_file": "a.md", "score": 2.0}]
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"q": "neural networks", "top_k": 5}


def test_list_dead_letters_returns_data():
    client = KnowledgeGraphClient()
    payload = [{"file": "20260726T150000_a.md.txt", "source_file": "a.md", "error": "timeout"}]
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response(payload)) as mock_get:
        result = client.list_dead_letters()
    assert result[0].file == "20260726T150000_a.md.txt"
    assert result[0].source_file == "a.md"
    assert result[0].error == "timeout"
    assert mock_get.call_args[0][0].endswith("/list_dead_letters")


def test_list_dead_letters_returns_empty_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        assert client.list_dead_letters() == []


def test_clear_dead_letters_returns_removed_count():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post",
               return_value=_mock_response({"removed": 3})) as mock_post:
        assert client.clear_dead_letters() == 3
    assert mock_post.call_args[0][0].endswith("/clear_dead_letters")


def test_clear_dead_letters_returns_zero_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post", side_effect=requests.ConnectionError("down")):
        assert client.clear_dead_letters() == 0


def test_entities_for_file_forwards_rel_path_and_returns_data():
    client = KnowledgeGraphClient()
    payload = {"entities": [{"id": "e1", "label": "E1"}], "edges": [], "extracted_by": "qwen2.5:7b"}
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response(payload)) as mock_get:
        result = client.entities_for_file("notes/a.md")
    assert result.entities[0].id == "e1"
    assert result.edges == []
    assert result.extracted_by == "qwen2.5:7b"
    assert mock_get.call_args.kwargs["params"] == {"rel": "notes/a.md"}


def test_entities_for_file_returns_empty_shape_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        result = client.entities_for_file("notes/a.md")
    assert result.entities == []
    assert result.edges == []


def test_ollama_ready_false_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        assert client._ollama_ready() is False


def test_ollama_ready_reflects_response():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", return_value=_mock_response({"reachable": True})):
        assert client._ollama_ready() is True


def test_ollama_deep_search_merges_graph_and_chroma_scores():
    client = KnowledgeGraphClient()
    chroma = MagicMock()
    chroma.query.return_value = [GraphSearchResult(source_file="b.md", score=0.9)]
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response([{"source_file": "a.md", "score": 2.0}])):
        results = client.ollama_deep_search("q", top_k=10, chroma=chroma)

    by_file = {r.source_file: r.score for r in results}
    assert by_file["a.md"] == 1.0  # normalized max score from graph ranking
    assert by_file["b.md"] == 0.9  # from chroma, no graph match


def test_ollama_deep_search_returns_empty_when_no_scores():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", return_value=_mock_response([])):
        assert client.ollama_deep_search("q") == []


def test_drop_index_posts_to_kg():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post") as mock_post:
        client.drop_index()
    assert mock_post.call_args[0][0].endswith("/drop_index")


def test_taint_file_forwards_rel_and_returns_tainted_flag():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post",
               return_value=_mock_response({"tainted": True})) as mock_post:
        assert client.taint_file("notes/a.md") is True
    assert mock_post.call_args.kwargs["params"] == {"rel": "notes/a.md"}


def test_taint_file_returns_false_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.post", side_effect=requests.ConnectionError("down")):
        assert client.taint_file("notes/a.md") is False


def test_ranked_nodes_passes_params_and_returns_results():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response([{"source_file": "a.md", "score": 1.5, "label": "A"}])) as mock_get:
        result = client.ranked_nodes("neural networks", top_k=5)
    assert [r.model_dump() for r in result] == [{"source_file": "a.md", "score": 1.5, "label": "A"}]
    assert mock_get.call_args.kwargs["params"] == {"q": "neural networks", "top_k": 5}


def test_ranked_nodes_returns_empty_list_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        assert client.ranked_nodes("q") == []


def test_query_passes_params_and_returns_results():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get",
               return_value=_mock_response([{"text": "some context"}])) as mock_get:
        result = client.query("neural networks", budget=500)
    assert [r.model_dump() for r in result] == [{"text": "some context", "sources": []}]
    assert mock_get.call_args.kwargs["params"] == {"q": "neural networks", "budget": 500}


def test_query_returns_empty_list_when_unreachable():
    client = KnowledgeGraphClient()
    with patch("prisma.services.knowledge_graph_client.requests.get", side_effect=requests.ConnectionError("down")):
        assert client.query("q") == []


def test_start_stop_are_safe_no_ops():
    client = KnowledgeGraphClient()
    client.start()
    client.stop()  # must not raise, no HTTP calls expected
