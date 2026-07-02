"""
Tests for _StreamScheduler._tick() selection logic and _run_stream() behavior.
All external boundaries (SearchAgent, ConfigLoader, network) are mocked.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from prisma.services.vault import VaultService
from prisma.services.zotero import ZoteroCollection, ZoteroItem, ZoteroMode
from prisma.storage.models.vault_models import StreamStatus, RefreshFrequency
from prisma.storage.models.agent_models import PaperMetadata, SearchResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_paper(**kwargs) -> PaperMetadata:
    defaults = dict(
        title="Test Paper",
        authors=["Smith J"],
        abstract="An abstract.",
        source="arxiv",
        url="https://arxiv.org/abs/1234.5678",
    )
    defaults.update(kwargs)
    return PaperMetadata(**defaults)


def _make_search_result(papers=None) -> SearchResult:
    return SearchResult(
        papers=papers or [],
        query="test",
        sources_used=["arxiv"],
        total_found=len(papers or []),
    )


# ── _StreamScheduler._tick() ──────────────────────────────────────────────────

class TestStreamSchedulerTick:
    """Tests for which streams _tick() decides to run."""

    @pytest.fixture
    def vault(self, tmp_path):
        v = VaultService(tmp_path)
        v.ensure_dirs()
        return v

    def _make_tick(self, vault):
        """Return a _tick function bound to the given vault, with _run_stream mocked."""
        import prisma.server.app as app_mod
        from prisma.server.app import _StreamScheduler

        scheduler = _StreamScheduler()
        calls = []

        def fake_run_stream(slug, force=False):
            calls.append(slug)
            from prisma.server.app import StreamRunResult
            return StreamRunResult(slug=slug, papers_found=0, papers_saved=0,
                                   sources_used=[], sources_skipped=[])

        return scheduler, calls, fake_run_stream

    def test_skips_paused_stream(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Paused", query="q")
        vault.save_stream("paused", status="paused")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert calls == []

    def test_skips_archived_stream(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Old", query="q")
        vault.save_stream("old", status="archived")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert calls == []

    def test_skips_manual_frequency(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Manual", query="q", refresh_frequency="manual")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert calls == []

    def test_skips_stream_not_yet_due(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Future", query="q")
        vault.save_stream("future", next_update=datetime.now() + timedelta(hours=2))

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert calls == []

    def test_runs_overdue_stream(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Overdue", query="q")
        vault.save_stream("overdue", next_update=datetime.now() - timedelta(hours=1))

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert "overdue" in calls

    def test_runs_stream_with_no_next_update(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Never Run", query="q")
        # next_update is None by default — treat as always due

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert "never-run" in calls

    def test_runs_only_due_streams_when_mixed(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Due", query="q")
        vault.save_stream("due", next_update=datetime.now() - timedelta(minutes=1))

        vault.create_stream(title="Not Due", query="q")
        vault.save_stream("not-due", next_update=datetime.now() + timedelta(days=3))

        vault.create_stream(title="Paused", query="q")
        vault.save_stream("paused", status="paused")

        scheduler, calls, fake_run = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", fake_run):
            scheduler._tick()

        assert calls == ["due"]

    def test_tick_continues_after_run_stream_error(self, vault):
        import prisma.server.app as app_mod
        vault.create_stream(title="Boom", query="q")
        vault.save_stream("boom", next_update=datetime.now() - timedelta(hours=1))

        vault.create_stream(title="Fine", query="q")
        vault.save_stream("fine", next_update=datetime.now() - timedelta(hours=1))

        calls = []

        def failing_run(slug, force=False):
            calls.append(slug)
            if slug == "boom":
                raise RuntimeError("network error")
            from prisma.server.app import StreamRunResult
            return StreamRunResult(slug=slug, papers_found=0, papers_saved=0,
                                   sources_used=[], sources_skipped=[])

        scheduler, _, _ = self._make_tick(vault)
        with patch.object(app_mod, "_vault", vault), \
             patch.object(app_mod, "_run_stream", failing_run):
            scheduler._tick()  # must not raise

        assert "fine" in calls


# ── _run_stream() ─────────────────────────────────────────────────────────────

class TestRunStream:
    """Tests for _run_stream() behavior."""

    @pytest.fixture
    def vault(self, tmp_path):
        v = VaultService(tmp_path)
        v.ensure_dirs()
        return v

    @pytest.fixture
    def mock_indexer(self):
        m = MagicMock()
        m.mark_stale = MagicMock()
        return m

    @pytest.fixture
    def mock_cfg(self):
        cfg = MagicMock()
        cfg.sources = ["arxiv"]
        cfg.default_limit = 10
        return cfg

    @pytest.fixture
    def mock_zotero(self):
        z = MagicMock()
        z.mode = ZoteroMode.web_api
        z.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="Test")
        z.list_items.return_value = []
        z.find_by_identifier.return_value = None
        z.add_item.return_value = MagicMock(key="ITEM1", version=0, collection_keys=[])
        return z

    def _patched_run(self, vault, indexer, cfg, agent_mock, zotero=None):
        """Return patches for all globals _run_stream touches."""
        import prisma.server.app as app_mod
        from prisma.storage.models.api_response_models import LLMRelevanceResult

        loader_mock = MagicMock()
        loader_mock.return_value.get_search_config.return_value = cfg

        agent_cls_mock = MagicMock(return_value=agent_mock)

        if zotero is None:
            zotero = MagicMock()
            zotero.mode = ZoteroMode.web_api
            zotero.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="Test")
            zotero.list_items.return_value = []
            zotero.find_by_identifier.return_value = None
            zotero.add_item.return_value = MagicMock(key="ITEM1", version=0, collection_keys=[])

        # AnalysisAgent makes real Ollama HTTP calls — mock it; all papers are relevant by default
        from prisma.storage.models.api_response_models import LLMIdentityResult
        analysis_mock = MagicMock()
        analysis_mock.assess_relevance.return_value = LLMRelevanceResult(
            is_relevant=True,
            relevance_level="RELEVANT",
            confidence=0.9,
            reasoning="mock",
            semantic_score=0.9,
        )
        # check_identity_batch returns one result per candidate — default to not-same
        analysis_mock.check_identity_batch.side_effect = (
            lambda title, abstract, candidates: [
                LLMIdentityResult(are_same=False, confidence=0.9, reason="mock")
                for _ in candidates
            ]
        )
        # batch_relevance_check returns True for each candidate — all relevant by default
        analysis_mock.batch_relevance_check.side_effect = (
            lambda query, candidates: [True for _ in candidates]
        )
        analysis_cls_mock = MagicMock(return_value=analysis_mock)

        return (
            patch.object(app_mod, "_vault", vault),
            patch.object(app_mod, "_indexer", indexer),
            patch.object(app_mod, "_zotero", zotero),
            patch("prisma.utils.config.ConfigLoader", loader_mock),
            patch("prisma.agents.search_agent.SearchAgent", agent_cls_mock),
            patch("prisma.agents.analysis_agent.AnalysisAgent", analysis_cls_mock),
        )

    def test_returns_not_due_when_next_update_in_future(self, vault, mock_indexer, mock_cfg):
        import prisma.server.app as app_mod
        vault.create_stream(title="Soon", query="q")
        vault.save_stream("soon", next_update=datetime.now() + timedelta(hours=1))

        agent = MagicMock()
        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            result = _run_stream("soon", force=False)

        assert result.papers_found == 0
        assert any("not due" in e for e in result.errors)
        agent.preflight.assert_not_called()

    def test_force_bypasses_not_due(self, vault, mock_indexer, mock_cfg):
        import prisma.server.app as app_mod
        vault.create_stream(title="Soon", query="q")
        vault.save_stream("soon", next_update=datetime.now() + timedelta(hours=1))

        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result()

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            result = _run_stream("soon", force=True)

        agent.preflight.assert_called_once()

    def test_raises_404_for_missing_stream(self, vault, mock_indexer, mock_cfg):
        from fastapi import HTTPException
        agent = MagicMock()
        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            with pytest.raises(HTTPException) as exc_info:
                _run_stream("does-not-exist")
        assert exc_info.value.status_code == 404

    def test_returns_early_when_all_sources_fail_preflight(self, vault, mock_indexer, mock_cfg):
        vault.create_stream(title="Net", query="q")

        agent = MagicMock()
        agent.preflight.return_value = []  # all fail

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            result = _run_stream("net", force=True)

        assert result.papers_found == 0
        assert result.papers_saved == 0
        assert any("preflight" in e for e in result.errors)
        agent.search.assert_not_called()

    def test_saves_new_papers_to_zotero(self, vault, mock_indexer, mock_cfg):
        vault.create_stream(title="AI", query="artificial intelligence")

        # Title shares stems with the query so it clears the stem pre-filter —
        # a title unrelated to the query (e.g. "Attention Is All You Need") is
        # exactly what that filter is meant to screen out before the LLM call.
        paper = _make_paper(title="Artificial Intelligence and Attention Mechanisms", authors=["Vaswani A"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        import prisma.server.app as app_mod
        zotero = MagicMock()
        zotero.mode = ZoteroMode.web_api
        zotero.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="AI")
        zotero.list_items.return_value = []
        zotero.find_by_identifier.return_value = None
        zotero.add_item.return_value = MagicMock(key="ITEM1", version=0, collection_keys=[])

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent, zotero=zotero)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            result = _run_stream("ai", force=True)

        assert result.papers_found == 1
        assert result.papers_saved == 1
        zotero.ensure_collection.assert_called_once()
        zotero.add_item.assert_called_once()
        zotero.add_to_collection.assert_called_once()

    def test_does_not_save_duplicate_papers(self, vault, mock_indexer, mock_cfg):
        vault.create_stream(title="AI", query="q")

        paper = _make_paper(title="Attention Is All You Need", authors=["Vaswani A"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        existing = ZoteroItem(
            key="EXISTING", title="Attention Is All You Need",
            item_type="preprint", authors=["Vaswani A"],
            year=2017, abstract=None, doi=None, url=None,
            publication=None, tags=[], collection_keys=["TESTCOLL"],
        )
        import prisma.server.app as app_mod
        zotero = MagicMock()
        zotero.mode = ZoteroMode.web_api
        zotero.ensure_collection.return_value = ZoteroCollection(key="TESTCOLL", name="AI")
        zotero.list_items.return_value = [existing]

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent, zotero=zotero)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            result = _run_stream("ai", force=True)

        assert result.papers_saved == 0
        zotero.add_item.assert_not_called()

    def test_updates_stream_metadata_after_run(self, vault, mock_indexer, mock_cfg):
        vault.create_stream(title="Meta", query="q", refresh_frequency="weekly")

        paper = _make_paper(title="A Paper", authors=["Doe J"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            _run_stream("meta", force=True)

        updated = vault.get_stream("meta")
        assert updated.total_papers == 1
        assert updated.last_updated is not None
        assert updated.next_update is not None
        assert updated.next_update > datetime.now()

    def test_does_not_mark_indexer_stale_on_stream_run(self, vault, mock_indexer, mock_cfg):
        # Stream runs write to Zotero, not the vault — indexer is never marked stale here.
        vault.create_stream(title="Index", query="q")

        paper = _make_paper(title="New Finding", authors=["Jones B"])
        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]
        agent.search.return_value = _make_search_result(papers=[paper])

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            _run_stream("index", force=True)

        mock_indexer.mark_stale.assert_not_called()

    def test_reports_skipped_sources(self, vault, mock_indexer, mock_cfg):
        mock_cfg.sources = ["arxiv", "semanticscholar"]
        vault.create_stream(title="Sources", query="q")

        agent = MagicMock()
        agent.preflight.return_value = ["arxiv"]  # semanticscholar fails preflight
        agent.search.return_value = _make_search_result()

        patches = self._patched_run(vault, mock_indexer, mock_cfg, agent)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            from prisma.server.app import _run_stream
            result = _run_stream("sources", force=True)

        assert "semanticscholar" in result.sources_skipped
        assert "arxiv" in result.sources_used
