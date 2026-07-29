"""Unit tests for app.py's _chat_blocked_reason -- checks whether the shared
local-ollama pool is busy with the kg indexer or chroma embedder before chat
tries to use it. Exercises the real KGStatus/ChromaStatus attribute access
(not dicts) since these come from kg.status()/chroma.status(), which return
typed models -- a bare `except Exception: pass` around dict-style .get()
access here would otherwise silently swallow an AttributeError and always
report "not blocked," which is exactly the kind of regression this guards
against.
"""
from unittest.mock import MagicMock

from prisma.server.app import _chat_blocked_reason
from prisma.storage.models.chroma_models import ChromaStatus
from prisma.storage.models.kg_models import KGStatus


def _kg_status(**overrides) -> KGStatus:
    defaults = dict(
        state="idle", last_indexed=None, last_error=None, current_activity=None,
        sync_total=0, sync_done=0, current_file=None,
        current_file_chunks_done=0, current_file_chunks_total=0,
        chunk_avg_duration_ms=None, chunk_duration_samples=0,
        chunk_avg_retries=None, chunk_avg_size_tokens=None,
        dropped_chunks_total=0, dropped_chunks_recent=[],
    )
    defaults.update(overrides)
    return KGStatus(**defaults)


def test_returns_none_when_both_idle():
    kg = MagicMock()
    kg.status.return_value = _kg_status(state="idle")
    chroma = MagicMock()
    chroma.status.return_value = ChromaStatus(
        chunks=0, files_indexed=0, model="nomic-embed-text", provider="ollama", current_activity=None,
    )
    assert _chat_blocked_reason(chroma, kg) is None


def test_returns_reason_when_kg_indexing():
    kg = MagicMock()
    kg.status.return_value = _kg_status(state="indexing")
    chroma = MagicMock()
    chroma.status.return_value = ChromaStatus(
        chunks=0, files_indexed=0, model="nomic-embed-text", provider="ollama", current_activity=None,
    )
    assert "knowledge graph" in _chat_blocked_reason(chroma, kg)


def test_returns_reason_when_chroma_active():
    kg = MagicMock()
    kg.status.return_value = _kg_status(state="idle")
    chroma = MagicMock()
    chroma.status.return_value = ChromaStatus(
        chunks=0, files_indexed=0, model="nomic-embed-text", provider="ollama",
        current_activity="embedding notes/foo.md",
    )
    assert "semantic search" in _chat_blocked_reason(chroma, kg)


def test_swallows_exceptions_from_either_status_call():
    kg = MagicMock()
    kg.status.side_effect = RuntimeError("kg unreachable")
    chroma = MagicMock()
    chroma.status.side_effect = RuntimeError("chroma unreachable")
    assert _chat_blocked_reason(chroma, kg) is None
