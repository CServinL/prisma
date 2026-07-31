"""Unit tests for the chat tool registry (pattern-based tool loop)."""
from unittest.mock import MagicMock

import pytest

from prisma.services.chat_tools import TOOL_CALL_RE, ChatToolbox, system_prompt_tool_section
from prisma.services.vault import VaultService
from prisma.storage.models.kg_models import GraphQueryResult
from prisma.storage.models.search_models import GraphSearchResult


def test_system_prompt_tool_section_includes_all_markers():
    text = system_prompt_tool_section()
    assert "SEARCH_VAULT:" in text
    assert "GRAPH_CONTEXT:" in text


def test_tool_call_re_matches_search_vault_line():
    text = "some preamble\nSEARCH_VAULT: attention mechanisms\nmore text"
    matches = TOOL_CALL_RE.findall(text)
    assert matches == [("SEARCH_VAULT", "attention mechanisms")]


def test_tool_call_re_matches_graph_context_line():
    text = "GRAPH_CONTEXT: sparse autoencoders and interpretability"
    matches = TOOL_CALL_RE.findall(text)
    assert matches == [("GRAPH_CONTEXT", "sparse autoencoders and interpretability")]


def test_tool_call_re_ignores_plain_prose():
    text = "LLM stands for Large Language Model."
    assert TOOL_CALL_RE.findall(text) == []


@pytest.fixture
def vault(tmp_path):
    v = VaultService(vault_root=tmp_path / "vault")
    v.ensure_dirs()
    return v


def test_toolbox_search_vault_returns_wrapped_text_and_raw(vault):
    note = vault.root / "notes" / "attention.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Attention mechanisms let models weigh input tokens.", encoding="utf-8")

    chroma = MagicMock()
    chroma.query.return_value = [GraphSearchResult(source_file="notes/attention.md", score=0.9)]
    kg = MagicMock()

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("SEARCH_VAULT", "attention")

    assert result.raw == [{"source_file": "notes/attention.md", "score": 0.9,
                            "text": "Attention mechanisms let models weigh input tokens."}]
    # Wrapped under the slug (ADR-017: what a footnote's `sources` expects),
    # not the raw vault-relative path.
    assert 'path="attention"' in result.text
    assert "Attention mechanisms" in result.text


def test_toolbox_search_vault_skips_unreadable_files(vault):
    chroma = MagicMock()
    chroma.query.return_value = [GraphSearchResult(source_file="notes/missing.md", score=0.5)]
    kg = MagicMock()

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("SEARCH_VAULT", "anything")

    assert result.text == ""
    assert result.raw[0]["text"] == ""


def test_toolbox_graph_context_returns_wrapped_text(vault):
    chroma = MagicMock()
    kg = MagicMock()
    kg.query.return_value = [GraphQueryResult(text="- notes/a.md (score=0.8)", sources=["a", "b"])]

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("GRAPH_CONTEXT", "how do these relate")

    assert "notes/a.md" in result.text
    assert 'path="knowledge-graph"' in result.text
    # ADR-017: sources listed explicitly so the model has an unambiguous
    # list to copy into FOOTNOTES_JSON, not just slugs buried in prose.
    assert "Sources: a, b" in result.text
    assert result.raw == [{"text": "- notes/a.md (score=0.8)", "sources": ["a", "b"]}]


def test_toolbox_graph_context_omits_sources_header_when_none(vault):
    chroma = MagicMock()
    kg = MagicMock()
    kg.query.return_value = [GraphQueryResult(text="- notes/a.md (score=0.8)")]

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("GRAPH_CONTEXT", "how do these relate")

    assert "Sources:" not in result.text


def test_toolbox_graph_context_empty_when_no_results(vault):
    chroma = MagicMock()
    kg = MagicMock()
    kg.query.return_value = []

    toolbox = ChatToolbox(chroma, kg, vault)
    result = toolbox.call("GRAPH_CONTEXT", "anything")

    assert result.text == ""
    assert result.raw == []


def test_toolbox_call_unknown_marker_raises(vault):
    toolbox = ChatToolbox(MagicMock(), MagicMock(), vault)
    with pytest.raises(ValueError, match="unknown tool marker"):
        toolbox.call("NOT_A_TOOL", "query")
