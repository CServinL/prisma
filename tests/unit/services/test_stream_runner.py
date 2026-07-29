"""Unit tests for prisma.services.stream_runner.run_stream -- the actual
stream-execution entrypoint (search -> dedup -> relevance -> save to
Zotero). Previously had zero direct tests despite being the function that
wires together everything else in this module.

Uses a real tmp_path-backed VaultService (same convention as
test_vault_streams.py -- no mocks for the vault itself), and mocks only the
external collaborators: SearchAgent, AnalysisAgent, ConfigLoader, and
ZoteroClient (a MagicMock, since the real one makes live Zotero API calls).
SearchAgent/AnalysisAgent are imported *inside* run_stream
(`from prisma.agents.search_agent import SearchAgent`), so they must be
patched at their source module, not at prisma.services.stream_runner.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from prisma.services.stream_runner import run_stream
from prisma.services.vault import VaultService


@pytest.fixture
def vault(tmp_path):
    v = VaultService(tmp_path)
    v.ensure_dirs()
    return v


def _paper(title, doi=None, abstract=""):
    p = MagicMock()
    p.title = title
    p.doi = doi
    p.abstract = abstract
    return p


def _zotero_item(key, title, doi=None, version=1, collections=None):
    item = MagicMock()
    item.key = key
    item.title = title
    item.doi = doi
    item.version = version
    item.collections = collections or []
    return item


def _search_config(sources=("arxiv",), default_limit=10):
    cfg = MagicMock()
    cfg.sources = list(sources)
    cfg.default_limit = default_limit
    return cfg


def test_not_due_skips_without_force(vault):
    stream = vault.create_stream(title="Test Stream", query="short query for prefilter bypass")
    future = datetime.now() + timedelta(days=1)
    vault.save_stream(stream.slug, next_update=future)

    zotero = MagicMock()
    with patch("prisma.agents.search_agent.SearchAgent") as MockSearchAgent:
        result = run_stream(stream.slug, vault, zotero, force=False)

    assert result.papers_found == 0
    assert result.papers_saved == 0
    assert any("not due" in e for e in result.errors)
    MockSearchAgent.assert_not_called()


def test_all_sources_fail_preflight(vault):
    stream = vault.create_stream(title="Test Stream", query="deep learning")
    zotero = MagicMock()

    mock_search_agent = MagicMock()
    mock_search_agent.preflight.return_value = []

    with patch("prisma.agents.search_agent.SearchAgent", return_value=mock_search_agent), \
         patch("prisma.utils.config.ConfigLoader") as MockConfigLoader:
        MockConfigLoader.return_value.get_search_config.return_value = _search_config()
        result = run_stream(stream.slug, vault, zotero, force=True)

    assert result.papers_found == 0
    assert any("preflight" in e for e in result.errors)
    mock_search_agent.search.assert_not_called()


def test_zotero_offline_finds_but_does_not_save(vault):
    stream = vault.create_stream(title="Test Stream", query="short")
    zotero = MagicMock()
    zotero.is_available.return_value = False

    mock_search_agent = MagicMock()
    mock_search_agent.preflight.return_value = ["arxiv"]
    mock_search_agent.search.return_value = MagicMock(
        papers=[_paper("Paper One"), _paper("Paper Two")]
    )

    with patch("prisma.agents.search_agent.SearchAgent", return_value=mock_search_agent), \
         patch("prisma.utils.config.ConfigLoader") as MockConfigLoader, \
         patch("prisma.agents.analysis_agent.AnalysisAgent") as MockAnalysisAgent:
        MockConfigLoader.return_value.get_search_config.return_value = _search_config()
        result = run_stream(stream.slug, vault, zotero, force=True)

    assert result.papers_found == 2
    assert result.papers_saved == 0
    assert any("offline" in e.lower() for e in result.errors)
    # Zotero offline -> the internet-paper loop breaks immediately, so
    # relevance checking (and any Zotero write) never happens.
    MockAnalysisAgent.return_value.batch_relevance_check.assert_not_called()
    zotero.add_paper.assert_not_called()


def test_saves_relevant_new_paper_via_zotero_online(vault):
    stream = vault.create_stream(title="Test Stream", query="short")
    zotero = MagicMock()
    zotero.is_available.return_value = True
    zotero.ensure_collection.return_value = MagicMock(key="COLLECTION1")
    zotero.get_collection_items.return_value = []  # empty existing collection
    zotero.find_by_identifier.return_value = None  # not already in library
    saved_item = _zotero_item("NEW1", "Paper One", version=1)
    zotero.add_paper.return_value = saved_item

    mock_search_agent = MagicMock()
    mock_search_agent.preflight.return_value = ["arxiv"]
    mock_search_agent.search.return_value = MagicMock(papers=[_paper("Paper One")])

    mock_analysis_agent = MagicMock()
    mock_analysis_agent.batch_relevance_check.return_value = [True]

    with patch("prisma.agents.search_agent.SearchAgent", return_value=mock_search_agent), \
         patch("prisma.utils.config.ConfigLoader") as MockConfigLoader, \
         patch("prisma.agents.analysis_agent.AnalysisAgent", return_value=mock_analysis_agent):
        MockConfigLoader.return_value.get_search_config.return_value = _search_config()
        result = run_stream(stream.slug, vault, zotero, force=True)

    assert result.papers_saved == 1
    assert result.papers_skipped_llm == 0
    zotero.add_paper.assert_called_once()
    zotero.add_item_to_collection.assert_called_once_with("NEW1", "COLLECTION1")

    # collection_key was persisted onto the stream (ensure_collection's
    # result differs from the stream's prior None collection_key)
    updated = vault.get_stream(stream.slug)
    assert updated.collection_key == "COLLECTION1"


def test_dedup_skips_paper_already_in_collection(vault):
    stream = vault.create_stream(title="Test Stream", query="short")
    zotero = MagicMock()
    zotero.is_available.return_value = True
    zotero.ensure_collection.return_value = MagicMock(key="COLLECTION1")
    # Already-known item with the exact same title as the "new" paper found
    # below -- find_duplicate's level-2 exact-title match should catch this.
    zotero.get_collection_items.return_value = [_zotero_item("EXISTING1", "Duplicate Paper")]

    mock_search_agent = MagicMock()
    mock_search_agent.preflight.return_value = ["arxiv"]
    mock_search_agent.search.return_value = MagicMock(papers=[_paper("Duplicate Paper")])

    mock_analysis_agent = MagicMock()

    with patch("prisma.agents.search_agent.SearchAgent", return_value=mock_search_agent), \
         patch("prisma.utils.config.ConfigLoader") as MockConfigLoader, \
         patch("prisma.agents.analysis_agent.AnalysisAgent", return_value=mock_analysis_agent):
        MockConfigLoader.return_value.get_search_config.return_value = _search_config()
        result = run_stream(stream.slug, vault, zotero, force=True)

    assert result.papers_saved == 0
    # never even reaches the bookmark/relevance-check stage for this paper
    zotero.add_paper.assert_not_called()
    mock_analysis_agent.batch_relevance_check.assert_not_called()


def test_llm_relevance_check_rejects_paper(vault):
    stream = vault.create_stream(title="Test Stream", query="short")
    zotero = MagicMock()
    zotero.is_available.return_value = True
    zotero.ensure_collection.return_value = MagicMock(key="COLLECTION1")
    zotero.get_collection_items.return_value = []
    zotero.find_by_identifier.return_value = None
    zotero.add_paper.return_value = _zotero_item("NEW1", "Irrelevant Paper")

    mock_search_agent = MagicMock()
    mock_search_agent.preflight.return_value = ["arxiv"]
    mock_search_agent.search.return_value = MagicMock(papers=[_paper("Irrelevant Paper")])

    mock_analysis_agent = MagicMock()
    mock_analysis_agent.batch_relevance_check.return_value = [False]

    with patch("prisma.agents.search_agent.SearchAgent", return_value=mock_search_agent), \
         patch("prisma.utils.config.ConfigLoader") as MockConfigLoader, \
         patch("prisma.agents.analysis_agent.AnalysisAgent", return_value=mock_analysis_agent):
        MockConfigLoader.return_value.get_search_config.return_value = _search_config()
        result = run_stream(stream.slug, vault, zotero, force=True)

    assert result.papers_saved == 0
    assert result.papers_skipped_llm == 1
    zotero.add_item_to_collection.assert_not_called()


def test_library_search_source_saves_relevant_existing_item(vault):
    # Source 1 (Zotero library search) is a structurally separate code path
    # from Source 2 (internet search) -- exercised here on its own by
    # letting the internet search return no papers at all.
    stream = vault.create_stream(title="Test Stream", query="short")
    zotero = MagicMock()
    zotero.is_available.return_value = True
    zotero.ensure_collection.return_value = MagicMock(key="COLLECTION1")

    library_item = _zotero_item("LIB1", "Library Paper", version=2, collections=["OTHER"])

    zotero.get_collection_items.return_value = []  # collection currently empty
    zotero.search_items.return_value = [library_item]  # library-wide search result

    mock_search_agent = MagicMock()
    mock_search_agent.preflight.return_value = ["arxiv"]
    mock_search_agent.search.return_value = MagicMock(papers=[])  # no internet results

    mock_analysis_agent = MagicMock()
    mock_analysis_agent.batch_relevance_check.return_value = [True]

    with patch("prisma.agents.search_agent.SearchAgent", return_value=mock_search_agent), \
         patch("prisma.utils.config.ConfigLoader") as MockConfigLoader, \
         patch("prisma.agents.analysis_agent.AnalysisAgent", return_value=mock_analysis_agent):
        MockConfigLoader.return_value.get_search_config.return_value = _search_config()
        result = run_stream(stream.slug, vault, zotero, force=True)

    assert result.papers_saved == 1
    zotero.add_item_to_collection.assert_called_once_with("LIB1", "COLLECTION1")
