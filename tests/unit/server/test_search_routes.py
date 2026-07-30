"""Unit tests for prisma.server.search_routes — built in isolation (a bare
FastAPI app wrapping just build_search_router + a tmp_path VaultService),
not the full prisma.server.app singleton, same approach as
test_sync_routes.py/test_notes_routes.py. Previously /search and
/search/deep had zero dedicated test coverage anywhere.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prisma.server.search_routes import build_search_router
from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


@pytest.fixture
def indexer() -> MagicMock:
    return MagicMock()


@pytest.fixture
def chroma() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(vault, indexer, chroma) -> TestClient:
    app = FastAPI()
    app.include_router(build_search_router(
        get_vault=lambda: vault,
        get_indexer=lambda: indexer,
        get_chroma=lambda: chroma,
    ))
    return TestClient(app)


class TestTextSearch:
    def test_no_results_for_empty_vault(self, client):
        r = client.get("/search", params={"q": "deep learning"})
        assert r.status_code == 200
        assert r.json() == []

    def test_finds_note_by_body_content(self, client, vault):
        vault.create_note("My Note", "this note is about deep learning architectures")
        r = client.get("/search", params={"q": "deep learning"})
        assert r.status_code == 200
        slugs = [item["slug"] for item in r.json()]
        assert "my-note" in slugs

    def test_title_match_scores_higher_than_body_only_match(self, client, vault):
        vault.create_note("Deep Learning Basics", "an unrelated body")
        vault.create_note("Other Note", "mentions deep learning once in passing")
        r = client.get("/search", params={"q": "deep learning"})
        results = r.json()
        assert results[0]["slug"] == "deep-learning-basics"

    def test_requires_nonempty_q(self, client):
        r = client.get("/search", params={"q": ""})
        assert r.status_code == 422

    def test_no_results_when_no_terms_match(self, client, vault):
        vault.create_note("My Note", "some content")
        r = client.get("/search", params={"q": "xyzzy-nonexistent-term"})
        assert r.json() == []


class TestDeepSearch:
    def test_uses_ollama_results_when_available(self, client, vault, indexer, chroma):
        vault.create_note("AI Paper", "body about neural networks")
        from prisma.storage.models.search_models import DeepSearchCandidate
        indexer.ollama_deep_search.return_value = [
            DeepSearchCandidate(source_file="ai-paper.md", score=0.9, reason="relevant")
        ]

        r = client.get("/search/deep", params={"q": "neural networks"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["slug"] == "ai-paper"
        assert data[0]["reason"] == "relevant"
        indexer.ollama_deep_search.assert_called_once_with("neural networks", top_k=15, chroma=chroma)

    def test_falls_back_to_graph_ranked_nodes_when_ollama_empty(self, client, vault, indexer):
        vault.create_note("Graph Paper", "body content")
        indexer.ollama_deep_search.return_value = []
        node = MagicMock(source_file="graph-paper.md", score=0.5, label="graph match")
        indexer.ranked_nodes.return_value = [node]

        r = client.get("/search/deep", params={"q": "graph content"})
        assert r.status_code == 200
        slugs = [item["slug"] for item in r.json()]
        assert "graph-paper" in slugs

    def test_falls_back_to_text_search_when_graph_not_built(self, client, vault, indexer):
        vault.create_note("Text Only", "plain text search fallback content")
        indexer.ollama_deep_search.return_value = []
        indexer.ranked_nodes.return_value = []

        r = client.get("/search/deep", params={"q": "plain text fallback"})
        assert r.status_code == 200
        slugs = [item["slug"] for item in r.json()]
        assert "text-only" in slugs

    def test_requires_nonempty_q(self, client):
        r = client.get("/search/deep", params={"q": ""})
        assert r.status_code == 422
