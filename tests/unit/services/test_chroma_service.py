"""Unit tests for ChromaIndexer and chroma_service helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from prisma.services.chroma_service import ChromaIndexer, _chunk_markdown, _embed_texts


# ── _chunk_markdown ───────────────────────────────────────────────────────────

def test_chunk_markdown_splits_by_heading():
    text = "# Intro\nsome text\n## Section A\nmore text\n## Section B\neven more"
    chunks = _chunk_markdown(text)
    assert len(chunks) == 3
    assert any("some text" in c for c in chunks)
    assert any("Section A" in c for c in chunks)
    assert any("Section B" in c for c in chunks)


def test_chunk_markdown_no_headings_returns_single_chunk():
    text = "No headings here. Just a paragraph."
    chunks = _chunk_markdown(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_markdown_large_section_splits():
    # A section larger than max_chunk should be split further
    body = "x" * 2000
    chunks = _chunk_markdown(body, max_chunk=100)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 100


def test_chunk_markdown_empty_text_returns_one_chunk():
    chunks = _chunk_markdown("", max_chunk=100)
    assert len(chunks) == 1


# ── _embed_texts ──────────────────────────────────────────────────────────────

def test_embed_texts_returns_embeddings_on_200():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
    with patch("prisma.services.chroma_service.requests.post", return_value=mock_resp):
        result = _embed_texts(["hello", "world"], model="nomic-embed-text")
    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_embed_texts_returns_none_on_non_200():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("prisma.services.chroma_service.requests.post", return_value=mock_resp):
        result = _embed_texts(["hello"], model="nomic-embed-text")
    assert result is None


def test_embed_texts_returns_none_on_exception():
    with patch("prisma.services.chroma_service.requests.post", side_effect=ConnectionError("down")):
        result = _embed_texts(["hello"], model="nomic-embed-text")
    assert result is None


# ── ChromaIndexer ─────────────────────────────────────────────────────────────

@pytest.fixture
def vault(tmp_path):
    from prisma.services.vault import VaultService
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


@pytest.fixture
def indexer(vault):
    return ChromaIndexer(vault, embedding_model="nomic-embed-text")


def _mock_chroma_collection():
    col = MagicMock()
    col.count.return_value = 0
    return col


def _mock_chroma_client(collection):
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return client


def test_status_returns_zero_on_empty_collection(indexer):
    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)
    with patch("chromadb.HttpClient", return_value=client):
        status = indexer.status()
    assert status["chunks"] == 0
    assert status["files_indexed"] == 0
    assert status["model"] == "nomic-embed-text"
    assert status["current_activity"] is None


def test_full_index_sets_activity_per_file_then_clears(indexer, vault):
    md_file = vault.root / "notes" / "test.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Title\nSome content here.", encoding="utf-8")

    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)
    embed = [[0.1] * 768]

    with patch("chromadb.HttpClient", return_value=client):
        indexer._ensure_client()
        with patch("prisma.services.chroma_service.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
             patch("prisma.services.chroma_service.resource_lock.release"), \
             patch("prisma.services.chroma_service._embed_texts", return_value=embed), \
             patch.object(indexer, "_set_activity", wraps=indexer._set_activity) as mock_set_activity:
            indexer._full_index()

    activities = [c.args[0] for c in mock_set_activity.call_args_list]
    assert any(a and "scanning file" in a and "test.md" in a for a in activities)
    assert activities[-1] is None  # cleared when done
    assert indexer.status()["current_activity"] is None


def test_query_empty_collection_returns_empty(indexer):
    col = _mock_chroma_collection()
    col.count.return_value = 0
    client = _mock_chroma_client(col)
    with patch("chromadb.HttpClient", return_value=client):
        result = indexer.query("test question", top_k=5)
    assert result == []


def test_query_returns_ranked_file_scores(indexer, vault):
    col = _mock_chroma_collection()
    col.count.return_value = 6
    col.query.return_value = {
        "metadatas": [[
            {"path": "notes/a.md", "chunk": 0},
            {"path": "notes/b.md", "chunk": 0},
            {"path": "notes/a.md", "chunk": 1},
        ]],
        "distances": [[0.1, 0.5, 0.3]],  # lower distance = more similar
    }
    client = _mock_chroma_client(col)
    embed = [[0.1] * 768]
    with patch("chromadb.HttpClient", return_value=client):
        # Must mock resource_lock — otherwise this hits whatever supervisor
        # happens to be reachable on the default port on the machine running
        # the tests (e.g. a real `prisma serve` the developer has up), which
        # is both flaky and an unintended side effect on production state.
        with patch("prisma.services.chroma_service.resource_lock.acquire", return_value=(True, "local-ollama", "req-1")), \
             patch("prisma.services.chroma_service.resource_lock.release"), \
             patch("prisma.services.chroma_service._embed_texts", return_value=embed):
            result = indexer.query("neural networks", top_k=5)

    assert len(result) == 2
    # a.md has best chunk at distance 0.1 → score 0.9; b.md at 0.5 → score 0.5
    assert result[0]["source_file"] == "notes/a.md"
    assert abs(result[0]["score"] - 0.9) < 1e-6
    assert result[1]["source_file"] == "notes/b.md"
    assert abs(result[1]["score"] - 0.5) < 1e-6


def test_upsert_file_updates_manifest(indexer, vault, tmp_path):
    md_file = vault.root / "notes" / "test.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Title\nSome content here.", encoding="utf-8")

    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)
    # "# Title\nSome content here." → 1 chunk after heading split
    embed = [[0.1] * 768]

    with patch("chromadb.HttpClient", return_value=client):
        indexer._ensure_client()
        with patch("prisma.services.chroma_service._embed_texts", return_value=embed):
            result = indexer._upsert_file(md_file)

    assert result is True
    rel = str(md_file.relative_to(vault.root))
    assert rel in indexer._manifest
    assert col.upsert.called


def test_upsert_file_skips_on_embedding_failure(indexer, vault):
    md_file = vault.root / "notes" / "bad.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Content\nSome text.", encoding="utf-8")

    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)

    with patch("chromadb.HttpClient", return_value=client):
        indexer._ensure_client()
        with patch("prisma.services.chroma_service._embed_texts", return_value=None):
            result = indexer._upsert_file(md_file)

    assert result is False
    assert not col.upsert.called


def test_upsert_file_skips_when_mtime_unchanged(indexer, vault):
    md_file = vault.root / "notes" / "test.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Title\nSome content here.", encoding="utf-8")

    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)
    embed = [[0.1] * 768]

    with patch("chromadb.HttpClient", return_value=client):
        indexer._ensure_client()
        with patch("prisma.services.chroma_service._embed_texts", return_value=embed) as mock_embed:
            first = indexer._upsert_file(md_file)
            # Simulates a spurious watchdog re-fire (e.g. a metadata-only touch on
            # WSL2) with no actual content change — mtime is identical.
            second = indexer._upsert_file(md_file)

    assert first is True
    assert second is False
    assert mock_embed.call_count == 1
    assert col.upsert.call_count == 1


def test_delete_file_removes_from_manifest(indexer, vault):
    md_file = vault.root / "notes" / "gone.md"
    rel = str(md_file.relative_to(vault.root))
    indexer._manifest[rel] = 12345.0

    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)

    with patch("chromadb.HttpClient", return_value=client):
        indexer._ensure_client()
        result = indexer._delete_file(md_file)

    assert result is True
    assert rel not in indexer._manifest
    col.delete.assert_called_once_with(where={"path": rel})


def test_query_skips_embed_when_lease_denied(indexer, vault):
    col = _mock_chroma_collection()
    col.count.return_value = 6
    client = _mock_chroma_client(col)

    with patch("chromadb.HttpClient", return_value=client):
        with patch("prisma.services.chroma_service.resource_lock.acquire", return_value=(False, None, None)):
            with patch("prisma.services.resource_lock.backoff.retry_with_backoff",
                       side_effect=lambda attempt, is_success, **kw: attempt()):
                with patch("prisma.services.chroma_service._embed_texts") as mock_embed:
                    result = indexer.query("neural networks", top_k=5)

    assert result == []
    assert not mock_embed.called


def test_full_index_skips_when_lease_denied(indexer, vault):
    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)

    with patch("chromadb.HttpClient", return_value=client):
        with patch("prisma.services.chroma_service.resource_lock.acquire", return_value=(False, None, None)):
            with patch("prisma.services.resource_lock.backoff.retry_with_backoff",
                       side_effect=lambda attempt, is_success, **kw: attempt()):
                with patch.object(indexer, "_upsert_file") as mock_upsert:
                    indexer._full_index()

    assert not mock_upsert.called


def test_save_and_load_manifest(indexer, vault):
    col = _mock_chroma_collection()
    client = _mock_chroma_client(col)

    with patch("chromadb.HttpClient", return_value=client):
        indexer._ensure_client()

    indexer._manifest["notes/x.md"] = 999.0
    indexer._save_manifest()

    assert indexer._manifest_path.exists()
    data = json.loads(indexer._manifest_path.read_text())
    assert data["notes/x.md"] == 999.0
